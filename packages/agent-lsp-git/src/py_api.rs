use crate::adapter::gix_adapter::GixGitAdapter;
use crate::port::GitPort;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::path::PathBuf;

/// Python-facing git service (port → gix adapter).
#[pyclass(name = "GitService")]
pub struct GitService {
    inner: GixGitAdapter,
}

#[pymethods]
impl GitService {
    #[new]
    fn new() -> Self {
        Self {
            inner: GixGitAdapter::new(),
        }
    }

    fn init_bare(&self, path: &str) -> PyResult<String> {
        let p = self
            .inner
            .init_bare(&PathBuf::from(path))
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(p.display().to_string())
    }

    #[pyo3(signature = (bare, worktree_path, ref_name="HEAD"))]
    fn add_worktree(&self, bare: &str, worktree_path: &str, ref_name: &str) -> PyResult<String> {
        let p = self
            .inner
            .add_worktree(
                &PathBuf::from(bare),
                &PathBuf::from(worktree_path),
                ref_name,
            )
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(p.display().to_string())
    }

    #[pyo3(signature = (worktree_path, message, paths=None))]
    fn commit(
        &self,
        worktree_path: &str,
        message: &str,
        paths: Option<Vec<String>>,
    ) -> PyResult<String> {
        let paths = paths.unwrap_or_default();
        self.inner
            .commit(&PathBuf::from(worktree_path), message, &paths)
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }

    fn clone_bare(&self, url: &str, bare_path: &str) -> PyResult<String> {
        let p = self
            .inner
            .clone_bare(url, &PathBuf::from(bare_path))
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(p.display().to_string())
    }

    fn import_local(&self, src: &str, bare_path: &str) -> PyResult<String> {
        let p = self
            .inner
            .import_local(&PathBuf::from(src), &PathBuf::from(bare_path))
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        Ok(p.display().to_string())
    }
}

#[pymodule]
fn agent_lsp_git(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<GitService>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::{PyAnyMethods, PyModule};
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn py_git_service_roundtrip() {
        let dir = tempdir().unwrap();
        Python::attach(|py| {
            let m = PyModule::new(py, "g").unwrap();
            agent_lsp_git(&m).unwrap();
            assert!(m.getattr("GitService").is_ok());

            let git = GitService::new();
            let bare = git
                .init_bare(dir.path().join("p.git").to_str().unwrap())
                .unwrap();
            let wt = git
                .add_worktree(&bare, dir.path().join("wt").to_str().unwrap(), "main")
                .unwrap();
            fs::write(PathBuf::from(&wt).join("a.txt"), b"x").unwrap();
            let cid = git.commit(&wt, "msg", Some(vec!["a.txt".into()])).unwrap();
            assert!(cid.len() >= 7);

            let bare2 = git
                .import_local(&wt, dir.path().join("from-local.git").to_str().unwrap())
                .unwrap();
            assert!(PathBuf::from(bare2).exists());
        });
    }
}
