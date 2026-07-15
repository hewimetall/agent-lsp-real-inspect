use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum ContainerError {
    #[error("{0}")]
    Message(String),
}

impl ContainerError {
    pub fn msg(s: impl Into<String>) -> Self {
        Self::Message(s.into())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunContainerRequest {
    pub image: String,
    pub cmd: Vec<String>,
    /// Host:container bind mounts, e.g. "/abs/ws:/work"
    pub binds: Vec<String>,
    pub workdir: Option<String>,
    pub env: Vec<String>,
    pub auto_remove: bool,
    /// Optional `uid:gid` so bind-mounted artifacts are host-writable.
    pub user: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunContainerResult {
    pub status_code: i64,
    pub logs: String,
    pub container_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StartPersistentRequest {
    pub image: String,
    pub cmd: Vec<String>,
    pub binds: Vec<String>,
    pub workdir: Option<String>,
    pub env: Vec<String>,
    /// Host port to publish for LSP TCP (optional).
    pub host_port: Option<u16>,
    /// Container port to publish (default 3737).
    pub container_port: Option<u16>,
    pub name: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersistentContainer {
    pub container_id: String,
    pub host_port: Option<u16>,
}

/// Application port for containers (one-shot builds + long-lived session runtimes).
pub trait ContainerRuntime: Send + Sync {
    fn run(&self, req: RunContainerRequest) -> Result<RunContainerResult, ContainerError>;
    fn start_persistent(
        &self,
        req: StartPersistentRequest,
    ) -> Result<PersistentContainer, ContainerError>;
    fn stop(&self, container_id: &str) -> Result<(), ContainerError>;
    fn remove(&self, container_id: &str) -> Result<(), ContainerError>;
    /// True iff Docker reports the container as currently running.
    fn is_running(&self, container_id: &str) -> Result<bool, ContainerError>;
}
