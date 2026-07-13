//! Hexagonal container layer: port + bollard adapter (no docker CLI).

mod adapter;
mod port;
mod py_api;

pub use adapter::bollard_adapter::BollardDockerAdapter;
pub use port::{
    ContainerError, ContainerRuntime, PersistentContainer, RunContainerRequest, RunContainerResult,
    StartPersistentRequest,
};
pub use py_api::DockerService;
