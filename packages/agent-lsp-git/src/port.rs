use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum GitError {
    #[error("{0}")]
    Message(String),
}

impl GitError {
    pub fn msg(s: impl Into<String>) -> Self {
        Self::Message(s.into())
    }
}

/// Application port for local git operations (no CLI, no push).
pub trait GitPort: Send + Sync {
    fn init_bare(&self, path: &Path) -> Result<PathBuf, GitError>;
    fn add_worktree(
        &self,
        bare: &Path,
        worktree_path: &Path,
        ref_name: &str,
    ) -> Result<PathBuf, GitError>;
    fn commit(
        &self,
        worktree_path: &Path,
        message: &str,
        paths: &[String],
    ) -> Result<String, GitError>;
    /// Clone a remote or local URL into a bare repo at `bare_path`.
    fn clone_bare(&self, url: &str, bare_path: &Path) -> Result<PathBuf, GitError>;
    /// Import an existing local git working tree / bare into `bare_path` (local clone --bare).
    fn import_local(&self, src: &Path, bare_path: &Path) -> Result<PathBuf, GitError>;
}
