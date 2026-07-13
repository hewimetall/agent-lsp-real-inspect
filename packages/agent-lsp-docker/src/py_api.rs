use crate::adapter::bollard_adapter::BollardDockerAdapter;
use crate::port::{
    ContainerRuntime, PersistentContainer, RunContainerRequest, StartPersistentRequest,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Python-facing docker service (port → bollard adapter).
#[pyclass(name = "DockerService")]
pub struct DockerService {
    inner: BollardDockerAdapter,
}

#[pymethods]
impl DockerService {
    #[new]
    fn new() -> PyResult<Self> {
        Ok(Self {
            inner: BollardDockerAdapter::new().map_err(|e| PyValueError::new_err(e.to_string()))?,
        })
    }

    #[pyo3(signature = (image, cmd, binds=None, workdir=None, env=None, auto_remove=true, user=None))]
    #[allow(clippy::too_many_arguments)]
    fn run<'py>(
        &self,
        py: Python<'py>,
        image: &str,
        cmd: Vec<String>,
        binds: Option<Vec<String>>,
        workdir: Option<String>,
        env: Option<Vec<String>>,
        auto_remove: bool,
        user: Option<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let req = RunContainerRequest {
            image: image.to_string(),
            cmd,
            binds: binds.unwrap_or_default(),
            workdir,
            env: env.unwrap_or_default(),
            auto_remove,
            user,
        };
        let res = self
            .inner
            .run(req)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let d = PyDict::new(py);
        d.set_item("status_code", res.status_code)?;
        d.set_item("logs", res.logs)?;
        d.set_item("container_id", res.container_id)?;
        Ok(d)
    }

    /// Start a long-lived container held by a session (does not wait/exit).
    #[pyo3(signature = (image, cmd, binds=None, workdir=None, env=None, host_port=None, container_port=None, name=None))]
    #[allow(clippy::too_many_arguments)]
    fn start_persistent<'py>(
        &self,
        py: Python<'py>,
        image: &str,
        cmd: Vec<String>,
        binds: Option<Vec<String>>,
        workdir: Option<String>,
        env: Option<Vec<String>>,
        host_port: Option<u16>,
        container_port: Option<u16>,
        name: Option<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let req = StartPersistentRequest {
            image: image.to_string(),
            cmd,
            binds: binds.unwrap_or_default(),
            workdir,
            env: env.unwrap_or_default(),
            host_port,
            container_port,
            name,
        };
        let res: PersistentContainer = self
            .inner
            .start_persistent(req)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let d = PyDict::new(py);
        d.set_item("container_id", res.container_id)?;
        d.set_item("host_port", res.host_port)?;
        Ok(d)
    }

    fn stop(&self, container_id: &str) -> PyResult<()> {
        self.inner
            .stop(container_id)
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }

    fn remove(&self, container_id: &str) -> PyResult<()> {
        self.inner
            .remove(container_id)
            .map_err(|e| PyValueError::new_err(e.to_string()))
    }
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<DockerService>()?;
    Ok(())
}
