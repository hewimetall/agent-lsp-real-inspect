//! Hexagonal git layer: port + gix adapter (no CLI, no push).

mod adapter;
mod port;
mod py_api;

pub use adapter::gix_adapter::GixGitAdapter;
pub use port::{GitError, GitPort};
pub use py_api::GitService;
