use crate::port::{GitError, GitPort};
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

/// gix-backed adapter — never shells out to `git`.
pub struct GixGitAdapter;

impl GixGitAdapter {
    pub fn new() -> Self {
        Self
    }
}

impl Default for GixGitAdapter {
    fn default() -> Self {
        Self::new()
    }
}

impl GitPort for GixGitAdapter {
    fn init_bare(&self, path: &Path) -> Result<PathBuf, GitError> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|e| GitError::msg(e.to_string()))?;
        }
        let repo = gix::init_bare(path).map_err(|e| GitError::msg(e.to_string()))?;
        // Seed empty commit on refs/heads/main so add_worktree can peel HEAD.
        seed_empty_main(&repo)?;
        Ok(repo.path().to_owned())
    }

    fn clone_bare(&self, url: &str, bare_path: &Path) -> Result<PathBuf, GitError> {
        if bare_path.exists() {
            return Err(GitError::msg(format!(
                "bare path already exists: {}",
                bare_path.display()
            )));
        }
        if let Some(parent) = bare_path.parent() {
            fs::create_dir_all(parent).map_err(|e| GitError::msg(e.to_string()))?;
        }
        let parsed = gix::Url::from_bytes(url.as_bytes().into())
            .map_err(|e| GitError::msg(format!("parse url: {e}")))?;
        let mut prepare = gix::prepare_clone(parsed, bare_path)
            .map_err(|e| GitError::msg(format!("prepare_clone: {e}")))?;
        // fetch_only keeps a bare-like object store (no worktree checkout).
        let (repo, _outcome) = prepare
            .fetch_only(gix::progress::Discard, &gix::interrupt::IS_INTERRUPTED)
            .map_err(|e| GitError::msg(format!("clone fetch: {e}")))?;
        // Ensure HEAD points at a branch we can worktree from.
        ensure_head_branch(&repo)?;
        Ok(repo.path().to_owned())
    }

    fn import_local(&self, src: &Path, bare_path: &Path) -> Result<PathBuf, GitError> {
        let src = src
            .canonicalize()
            .map_err(|e| GitError::msg(format!("canonicalize {}: {e}", src.display())))?;
        // Open to validate it is a git repo (worktree or bare).
        let _ = gix::open(&src).map_err(|e| GitError::msg(format!("open local git: {e}")))?;
        let url = format!("file://{}", src.display());
        self.clone_bare(&url, bare_path)
    }

    fn add_worktree(
        &self,
        bare: &Path,
        worktree_path: &Path,
        ref_name: &str,
    ) -> Result<PathBuf, GitError> {
        let bare = bare.canonicalize().unwrap_or_else(|_| bare.to_path_buf());
        let repo = gix::open(&bare).map_err(|e| GitError::msg(format!("open bare: {e}")))?;

        if worktree_path.exists()
            && worktree_path
                .read_dir()
                .map(|mut d| d.next().is_some())
                .unwrap_or(false)
        {
            return Err(GitError::msg(format!(
                "worktree path not empty: {}",
                worktree_path.display()
            )));
        }
        fs::create_dir_all(worktree_path).map_err(|e| GitError::msg(e.to_string()))?;

        let name = worktree_path
            .file_name()
            .and_then(|s| s.to_str())
            .ok_or_else(|| GitError::msg("invalid worktree path"))?;

        let wt_git_dir = bare.join("worktrees").join(name);
        fs::create_dir_all(&wt_git_dir).map_err(|e| GitError::msg(e.to_string()))?;

        // Resolve ref → object id (follow real HEAD when asked for HEAD).
        let branch_ref = resolve_branch_ref(&repo, ref_name)?;
        let mut head = repo
            .find_reference(&branch_ref)
            .or_else(|_| repo.find_reference("HEAD"))
            .map_err(|e| GitError::msg(format!("resolve ref {ref_name}: {e}")))?;
        let id = head
            .peel_to_id_in_place()
            .map_err(|e| GitError::msg(format!("peel: {e}")))?;
        let commit = repo
            .find_object(id)
            .map_err(|e| GitError::msg(format!("object: {e}")))?
            .peel_to_commit()
            .map_err(|e| GitError::msg(format!("commit: {e}")))?;
        let tree_id = commit.tree_id().map_err(|e| GitError::msg(e.to_string()))?;

        // Linked worktree metadata (git worktree layout, no CLI)
        let abs_wt = worktree_path
            .canonicalize()
            .unwrap_or_else(|_| worktree_path.to_path_buf());
        write_file(
            &wt_git_dir.join("gitdir"),
            format!("{}\n", abs_wt.join(".git").display()),
        )?;
        write_file(&wt_git_dir.join("commondir"), "../..\n")?;
        // Symbolic HEAD so commits update the shared branch on the bare repo.
        write_file(&wt_git_dir.join("HEAD"), format!("ref: {branch_ref}\n"))?;

        write_file(
            &worktree_path.join(".git"),
            format!("gitdir: {}\n", wt_git_dir.display()),
        )?;

        // Materialize files from tree (best-effort checkout)
        checkout_tree_to(&repo, tree_id.detach(), worktree_path)?;

        Ok(abs_wt)
    }

    fn commit(
        &self,
        worktree_path: &Path,
        message: &str,
        paths: &[String],
    ) -> Result<String, GitError> {
        let repo =
            gix::open(worktree_path).map_err(|e| GitError::msg(format!("open worktree: {e}")))?;

        if paths.is_empty() {
            return Err(GitError::msg(
                "commit requires at least one path in v1 (stage explicit paths)",
            ));
        }

        let abs_wt = worktree_path
            .canonicalize()
            .map_err(|e| GitError::msg(format!("canonicalize worktree: {e}")))?;

        let mut safe_paths: Vec<(String, PathBuf)> = Vec::new();
        for p in paths {
            let rel = p.replace('\\', "/");
            if Path::new(&rel).is_absolute() || rel.split('/').any(|c| c == "..") {
                return Err(GitError::msg(format!("path escapes worktree: {p}")));
            }
            let full = abs_wt.join(&rel);
            let canon = full
                .canonicalize()
                .map_err(|e| GitError::msg(format!("canonicalize {p}: {e}")))?;
            if !canon.starts_with(&abs_wt) {
                return Err(GitError::msg(format!("path escapes worktree: {p}")));
            }
            if !canon.is_file() {
                return Err(GitError::msg(format!("missing file for commit: {p}")));
            }
            safe_paths.push((rel, canon));
        }

        // Start from existing HEAD tree (merge), then overlay listed paths.
        let mut root = Node::default();
        if let Ok(head) = repo.head_id() {
            if let Ok(obj) = repo.find_object(head.detach()) {
                if let Ok(commit) = obj.peel_to_commit() {
                    if let Ok(tree_id) = commit.tree_id() {
                        load_tree_into_node(&repo, tree_id.detach(), &mut root)?;
                    }
                }
            }
        }

        for (rel, canon) in &safe_paths {
            let bytes = fs::read(canon).map_err(|e| GitError::msg(e.to_string()))?;
            let blob_id = repo
                .write_blob(&bytes)
                .map_err(|e| GitError::msg(format!("write blob: {e}")))?
                .detach();
            upsert_path(&mut root, rel, blob_id);
        }

        let tree_id = write_node(&repo, &root)?;
        let author = gix::actor::Signature {
            name: "agent-lsp-git".into(),
            email: "agent-lsp-git@localhost".into(),
            time: gix::date::Time::now_local_or_utc(),
        };
        let mut author_buf = gix_date::parse::TimeBuf::default();
        let mut committer_buf = gix_date::parse::TimeBuf::default();
        let author_ref = author.to_ref(&mut author_buf);
        let committer_ref = author.to_ref(&mut committer_buf);

        let parent = repo.head_id().ok().map(|id| id.detach());
        let mut parents: Vec<gix::ObjectId> = Vec::new();
        if let Some(p) = parent {
            parents.push(p);
        }

        let commit_id = repo
            .commit_as(
                committer_ref,
                author_ref,
                "HEAD",
                message,
                tree_id,
                parents.iter().copied(),
            )
            .map_err(|e| GitError::msg(format!("commit: {e}")))?;

        Ok(commit_id.to_string())
    }
}

fn resolve_branch_ref(repo: &gix::Repository, ref_name: &str) -> Result<String, GitError> {
    if ref_name != "HEAD" && !ref_name.is_empty() {
        return Ok(normalize_branch_ref(ref_name));
    }
    // Follow symbolic HEAD when present (main/master/…).
    if let Ok(head) = repo.head() {
        if let Some(name) = head.referent_name() {
            return Ok(name.as_bstr().to_string());
        }
    }
    if repo.find_reference("refs/heads/main").is_ok() {
        return Ok("refs/heads/main".to_string());
    }
    if repo.find_reference("refs/heads/master").is_ok() {
        return Ok("refs/heads/master".to_string());
    }
    Ok("refs/heads/main".to_string())
}

fn normalize_branch_ref(ref_name: &str) -> String {
    if ref_name == "HEAD" || ref_name.is_empty() {
        "refs/heads/main".to_string()
    } else if ref_name.starts_with("refs/") {
        ref_name.to_string()
    } else {
        format!("refs/heads/{ref_name}")
    }
}

fn ensure_head_branch(repo: &gix::Repository) -> Result<(), GitError> {
    // Prefer existing HEAD; if detached/missing, point at refs/heads/main when present.
    if repo.head_id().is_ok() {
        return Ok(());
    }
    if repo.find_reference("refs/heads/main").is_ok() {
        write_file(&repo.path().join("HEAD"), "ref: refs/heads/main\n")?;
    }
    Ok(())
}

/// Create an empty-tree commit on `refs/heads/main` and point HEAD at it.
fn seed_empty_main(repo: &gix::Repository) -> Result<(), GitError> {
    let tree = gix::objs::Tree::empty();
    let tree_id = repo
        .write_object(&tree)
        .map_err(|e| GitError::msg(format!("write empty tree: {e}")))?
        .detach();

    let author = gix::actor::Signature {
        name: "agent-lsp-git".into(),
        email: "agent-lsp-git@localhost".into(),
        time: gix::date::Time::now_local_or_utc(),
    };
    let mut author_buf = gix_date::parse::TimeBuf::default();
    let mut committer_buf = gix_date::parse::TimeBuf::default();
    let author_ref = author.to_ref(&mut author_buf);
    let committer_ref = author.to_ref(&mut committer_buf);

    let parents: Vec<gix::ObjectId> = Vec::new();
    repo.commit_as(
        committer_ref,
        author_ref,
        "refs/heads/main",
        "initial empty commit",
        tree_id,
        parents.iter().copied(),
    )
    .map_err(|e| GitError::msg(format!("seed commit: {e}")))?;

    // Ensure symbolic HEAD → refs/heads/main (gix init_bare usually does this).
    let head_path = repo.path().join("HEAD");
    if !head_path.exists() {
        write_file(&head_path, "ref: refs/heads/main\n")?;
    }
    Ok(())
}

fn write_file(path: &Path, content: impl AsRef<[u8]>) -> Result<(), GitError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| GitError::msg(e.to_string()))?;
    }
    let mut f = fs::File::create(path).map_err(|e| GitError::msg(e.to_string()))?;
    f.write_all(content.as_ref())
        .map_err(|e| GitError::msg(e.to_string()))?;
    Ok(())
}

fn checkout_tree_to(
    repo: &gix::Repository,
    tree_id: gix::ObjectId,
    dest: &Path,
) -> Result<(), GitError> {
    // Recursively checkout tree entries as files/dirs (simple, no filters).
    fn walk(repo: &gix::Repository, tree_id: gix::ObjectId, base: &Path) -> Result<(), GitError> {
        let tree = repo
            .find_object(tree_id)
            .map_err(|e| GitError::msg(e.to_string()))?
            .peel_to_tree()
            .map_err(|e| GitError::msg(e.to_string()))?;
        for entry in tree.iter() {
            let entry = entry.map_err(|e| GitError::msg(e.to_string()))?;
            let name = entry.filename().to_string();
            let path = base.join(&name);
            let mode = entry.mode();
            let oid = entry.oid().to_owned();
            if mode.is_tree() {
                fs::create_dir_all(&path).map_err(|e| GitError::msg(e.to_string()))?;
                walk(repo, oid, &path)?;
            } else if mode.is_blob() || mode.is_executable() {
                if let Some(parent) = path.parent() {
                    fs::create_dir_all(parent).map_err(|e| GitError::msg(e.to_string()))?;
                }
                let obj = repo
                    .find_object(oid)
                    .map_err(|e| GitError::msg(e.to_string()))?;
                let blob = obj
                    .try_into_blob()
                    .map_err(|e| GitError::msg(e.to_string()))?;
                fs::write(&path, blob.data.as_slice()).map_err(|e| GitError::msg(e.to_string()))?;
                #[cfg(unix)]
                if mode.is_executable() {
                    use std::os::unix::fs::PermissionsExt;
                    let mut perms = fs::metadata(&path)
                        .map_err(|e| GitError::msg(e.to_string()))?
                        .permissions();
                    perms.set_mode(0o755);
                    fs::set_permissions(&path, perms).map_err(|e| GitError::msg(e.to_string()))?;
                }
            }
        }
        Ok(())
    }
    walk(repo, tree_id, dest)
}

#[cfg_attr(not(test), allow(dead_code))]
fn write_flat_tree(
    repo: &gix::Repository,
    entries: &[(String, gix::ObjectId)],
) -> Result<gix::ObjectId, GitError> {
    let mut root = Node::default();
    for (path, oid) in entries {
        upsert_path(&mut root, path, *oid);
    }
    write_node(repo, &root)
}

#[derive(Default)]
struct Node {
    files: std::collections::BTreeMap<String, gix::ObjectId>,
    dirs: std::collections::BTreeMap<String, Node>,
}

fn upsert_path(root: &mut Node, path: &str, oid: gix::ObjectId) {
    let parts: Vec<&str> = path.split('/').filter(|p| !p.is_empty()).collect();
    if parts.is_empty() {
        return;
    }
    let mut node = root;
    for part in &parts[..parts.len() - 1] {
        node = node.dirs.entry((*part).to_string()).or_default();
    }
    node.files.insert(parts[parts.len() - 1].to_string(), oid);
}

fn load_tree_into_node(
    repo: &gix::Repository,
    tree_id: gix::ObjectId,
    node: &mut Node,
) -> Result<(), GitError> {
    let tree = repo
        .find_object(tree_id)
        .map_err(|e| GitError::msg(e.to_string()))?
        .peel_to_tree()
        .map_err(|e| GitError::msg(e.to_string()))?;
    for entry in tree.iter() {
        let entry = entry.map_err(|e| GitError::msg(e.to_string()))?;
        let name = entry.filename().to_string();
        let oid = entry.oid().to_owned();
        let mode = entry.mode();
        if mode.is_tree() {
            let child = node.dirs.entry(name).or_default();
            load_tree_into_node(repo, oid, child)?;
        } else if mode.is_blob() || mode.is_executable() {
            node.files.insert(name, oid);
        }
    }
    Ok(())
}

fn write_node(repo: &gix::Repository, node: &Node) -> Result<gix::ObjectId, GitError> {
    let mut tree = gix::objs::Tree::empty();
    for (name, oid) in &node.files {
        tree.entries.push(gix::objs::tree::Entry {
            mode: gix::objs::tree::EntryKind::Blob.into(),
            filename: name.as_str().into(),
            oid: *oid,
        });
    }
    for (name, child) in &node.dirs {
        let child_id = write_node(repo, child)?;
        tree.entries.push(gix::objs::tree::Entry {
            mode: gix::objs::tree::EntryKind::Tree.into(),
            filename: name.as_str().into(),
            oid: child_id,
        });
    }
    tree.entries.sort_by(|a, b| a.filename.cmp(&b.filename));
    Ok(repo
        .write_object(&tree)
        .map_err(|e| GitError::msg(format!("write tree: {e}")))?
        .detach())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::port::GitPort;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn init_worktree_commit_roundtrip() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("demo.git")).unwrap();
        let wt = git
            .add_worktree(&bare, &dir.path().join("wt"), "main")
            .unwrap();
        fs::write(wt.join("presentation.ir.json"), b"{\"title\":\"T\"}").unwrap();
        let cid = git
            .commit(&wt, "add ir", &["presentation.ir.json".into()])
            .unwrap();
        assert!(cid.len() >= 7);

        let wt2 = git
            .add_worktree(&bare, &dir.path().join("wt2"), "refs/heads/main")
            .unwrap();
        assert!(wt2.join("presentation.ir.json").is_file());
    }

    #[test]
    fn commit_errors_and_nested_paths() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("b.git")).unwrap();
        let wt = git.add_worktree(&bare, &dir.path().join("wt"), "").unwrap();
        assert!(git.commit(&wt, "x", &[]).is_err());
        assert!(git.commit(&wt, "x", &["missing.txt".into()]).is_err());

        fs::create_dir_all(wt.join("sub")).unwrap();
        fs::write(wt.join("sub/file.txt"), b"hi").unwrap();
        let cid = git.commit(&wt, "nested", &["sub/file.txt".into()]).unwrap();
        assert!(!cid.is_empty());
    }

    #[test]
    fn reject_non_empty_worktree() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("b.git")).unwrap();
        let wt = dir.path().join("wt");
        fs::create_dir_all(&wt).unwrap();
        fs::write(wt.join("x"), b"1").unwrap();
        assert!(git.add_worktree(&bare, &wt, "main").is_err());
    }

    #[test]
    fn commit_merges_existing_tree_and_rejects_escape() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("b.git")).unwrap();
        let wt = git
            .add_worktree(&bare, &dir.path().join("wt"), "main")
            .unwrap();
        fs::write(wt.join("a.txt"), b"a").unwrap();
        git.commit(&wt, "a", &["a.txt".into()]).unwrap();
        fs::write(wt.join("b.txt"), b"b").unwrap();
        git.commit(&wt, "b", &["b.txt".into()]).unwrap();
        let wt2 = git
            .add_worktree(&bare, &dir.path().join("wt2"), "main")
            .unwrap();
        assert!(wt2.join("a.txt").is_file());
        assert!(wt2.join("b.txt").is_file());

        assert!(git
            .commit(&wt, "evil", &["../outside.txt".into()])
            .is_err());
        assert!(git
            .commit(&wt, "evil", &["/etc/passwd".into()])
            .is_err());
    }

    #[test]
    fn normalize_branch_ref_variants() {
        assert_eq!(normalize_branch_ref("HEAD"), "refs/heads/main");
        assert_eq!(normalize_branch_ref(""), "refs/heads/main");
        assert_eq!(normalize_branch_ref("refs/heads/dev"), "refs/heads/dev");
        assert_eq!(normalize_branch_ref("feature"), "refs/heads/feature");
    }

    #[test]
    fn init_bare_fails_when_parent_is_file() {
        let dir = tempdir().unwrap();
        let blocker = dir.path().join("file");
        fs::write(&blocker, b"x").unwrap();
        let git = GixGitAdapter::new();
        assert!(git.init_bare(&blocker.join("repo.git")).is_err());
    }

    #[test]
    fn checkout_nested_and_executable_blob() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("b.git")).unwrap();
        let wt = git
            .add_worktree(&bare, &dir.path().join("wt"), "main")
            .unwrap();
        fs::create_dir_all(wt.join("bin")).unwrap();
        fs::write(wt.join("bin/tool"), b"#!/bin/sh\n").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut perms = fs::metadata(wt.join("bin/tool")).unwrap().permissions();
            perms.set_mode(0o755);
            fs::set_permissions(wt.join("bin/tool"), perms).unwrap();
        }
        // Commit as regular blob then rewrite tree entry as executable via gix for checkout coverage.
        git.commit(&wt, "tool", &["bin/tool".into()]).unwrap();

        // Build a commit with an executable-mode tree entry and checkout into wt3.
        let repo = gix::open(&bare).unwrap();
        let bytes = b"#!/bin/sh\necho hi\n";
        let blob = repo.write_blob(bytes).unwrap().detach();
        let mut tree = gix::objs::Tree::empty();
        tree.entries.push(gix::objs::tree::Entry {
            mode: gix::objs::tree::EntryKind::BlobExecutable.into(),
            filename: "run.sh".into(),
            oid: blob,
        });
        let tree_id = repo.write_object(&tree).unwrap().detach();
        let author = gix::actor::Signature {
            name: "t".into(),
            email: "t@t".into(),
            time: gix::date::Time::now_local_or_utc(),
        };
        let mut ab = gix_date::parse::TimeBuf::default();
        let mut cb = gix_date::parse::TimeBuf::default();
        let parent = repo.head_id().unwrap().detach();
        repo.commit_as(
            author.to_ref(&mut cb),
            author.to_ref(&mut ab),
            "refs/heads/main",
            "exec",
            tree_id,
            std::iter::once(parent),
        )
        .unwrap();

        let wt3 = git
            .add_worktree(&bare, &dir.path().join("wt3"), "main")
            .unwrap();
        assert!(wt3.join("run.sh").is_file());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(wt3.join("run.sh"))
                .unwrap()
                .permissions()
                .mode();
            assert_eq!(mode & 0o111, 0o111);
        }
    }

    #[test]
    fn write_flat_tree_skips_empty_path_components() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("b.git")).unwrap();
        let repo = gix::open(&bare).unwrap();
        let blob = repo.write_blob(b"x").unwrap().detach();
        let id = write_flat_tree(&repo, &[("/".into(), blob), ("ok.txt".into(), blob)]).unwrap();
        let _ = id;
    }

    #[test]
    fn checkout_preserves_nested_tree() {
        let dir = tempdir().unwrap();
        let git = GixGitAdapter::new();
        let bare = git.init_bare(&dir.path().join("b.git")).unwrap();
        let wt = git
            .add_worktree(&bare, &dir.path().join("wt"), "main")
            .unwrap();
        fs::create_dir_all(wt.join("a/b")).unwrap();
        fs::write(wt.join("a/b/c.txt"), b"nested").unwrap();
        git.commit(&wt, "nest", &["a/b/c.txt".into()]).unwrap();
        let wt2 = git
            .add_worktree(&bare, &dir.path().join("wt-nest"), "main")
            .unwrap();
        assert_eq!(fs::read_to_string(wt2.join("a/b/c.txt")).unwrap(), "nested");
    }

    #[test]
    fn git_error_display() {
        assert_eq!(crate::port::GitError::msg("boom").to_string(), "boom");
    }
}
