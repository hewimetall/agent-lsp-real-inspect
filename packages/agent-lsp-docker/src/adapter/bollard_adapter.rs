use crate::port::{
    ContainerError, ContainerRuntime, PersistentContainer, RunContainerRequest, RunContainerResult,
    StartPersistentRequest,
};
use bollard::container::{
    Config, CreateContainerOptions, LogOutput, LogsOptions, RemoveContainerOptions,
    StartContainerOptions, StopContainerOptions, WaitContainerOptions,
};
use bollard::models::{HostConfig, PortBinding};
use bollard::Docker;
use futures_util::StreamExt;
use std::collections::HashMap;
use tokio::runtime::Runtime;

/// bollard-backed adapter — talks to Docker Engine API (DooD socket), never CLI.
pub struct BollardDockerAdapter {
    rt: Runtime,
}

impl BollardDockerAdapter {
    pub fn new() -> Result<Self, ContainerError> {
        let rt = Runtime::new().map_err(|e| ContainerError::msg(e.to_string()))?;
        Ok(Self { rt })
    }
}

impl ContainerRuntime for BollardDockerAdapter {
    fn run(&self, req: RunContainerRequest) -> Result<RunContainerResult, ContainerError> {
        self.rt.block_on(async move { run_async(req).await })
    }

    fn start_persistent(
        &self,
        req: StartPersistentRequest,
    ) -> Result<PersistentContainer, ContainerError> {
        self.rt
            .block_on(async move { start_persistent_async(req).await })
    }

    fn stop(&self, container_id: &str) -> Result<(), ContainerError> {
        self.rt.block_on(async move {
            let docker = Docker::connect_with_local_defaults()
                .map_err(|e| ContainerError::msg(format!("connect docker: {e}")))?;
            docker
                .stop_container(container_id, Some(StopContainerOptions { t: 10 }))
                .await
                .map_err(|e| ContainerError::msg(format!("stop: {e}")))
        })
    }

    fn remove(&self, container_id: &str) -> Result<(), ContainerError> {
        self.rt.block_on(async move {
            let docker = Docker::connect_with_local_defaults()
                .map_err(|e| ContainerError::msg(format!("connect docker: {e}")))?;
            docker
                .remove_container(
                    container_id,
                    Some(RemoveContainerOptions {
                        force: true,
                        ..Default::default()
                    }),
                )
                .await
                .map_err(|e| ContainerError::msg(format!("remove: {e}")))
        })
    }
}

pub(crate) fn apply_wait_result(
    status_code: &mut i64,
    wait_err: &mut Option<String>,
    msg: Result<i64, String>,
) -> bool {
    match msg {
        Ok(code) => {
            *status_code = code;
            false
        }
        Err(e) => {
            *wait_err = Some(e);
            true
        }
    }
}

pub(crate) fn resolve_status_code(
    status_code: i64,
    wait_err: Option<String>,
    inspected_exit: Option<i64>,
) -> Result<i64, ContainerError> {
    let mut code = status_code;
    if code < 0 {
        if let Some(c) = inspected_exit {
            code = c;
        }
    }
    if code < 0 {
        if let Some(e) = wait_err {
            return Err(ContainerError::msg(format!("wait: {e}")));
        }
    }
    Ok(code)
}

pub(crate) fn append_log_item(
    logs: &mut String,
    item: Result<LogOutput, bollard::errors::Error>,
) -> bool {
    match item {
        Ok(LogOutput::StdOut { message }) | Ok(LogOutput::StdErr { message }) => {
            logs.push_str(&String::from_utf8_lossy(&message));
            false
        }
        Ok(_) => false,
        Err(e) => {
            logs.push_str(&format!("\n[log error: {e}]"));
            true
        }
    }
}

async fn run_async(req: RunContainerRequest) -> Result<RunContainerResult, ContainerError> {
    let docker = Docker::connect_with_local_defaults()
        .map_err(|e| ContainerError::msg(format!("connect docker: {e}")))?;

    let host_config = HostConfig {
        binds: Some(req.binds.clone()),
        auto_remove: Some(false),
        ..Default::default()
    };

    let config = Config {
        image: Some(req.image.clone()),
        cmd: Some(req.cmd.clone()),
        working_dir: req.workdir.clone(),
        user: req.user.clone(),
        env: if req.env.is_empty() {
            None
        } else {
            Some(req.env.clone())
        },
        host_config: Some(host_config),
        ..Default::default()
    };

    let created = docker
        .create_container(None::<CreateContainerOptions<String>>, config)
        .await
        .map_err(|e| ContainerError::msg(format!("create: {e}")))?;
    let id = created.id;

    docker
        .start_container(&id, None::<StartContainerOptions<String>>)
        .await
        .map_err(|e| ContainerError::msg(format!("start: {e}")))?;

    let mut wait_stream = docker.wait_container(
        &id,
        Some(WaitContainerOptions {
            condition: "not-running",
        }),
    );
    let mut status_code: i64 = -1;
    let mut wait_err: Option<String> = None;
    while let Some(msg) = wait_stream.next().await {
        let mapped = msg.map(|m| m.status_code).map_err(|e| e.to_string());
        if apply_wait_result(&mut status_code, &mut wait_err, mapped) {
            break;
        }
    }
    let mut inspected_exit: Option<i64> = None;
    if status_code < 0 {
        if let Ok(inspect) = docker.inspect_container(&id, None).await {
            if let Some(state) = inspect.state {
                inspected_exit = state.exit_code;
            }
        }
    }
    let status_code = resolve_status_code(status_code, wait_err, inspected_exit)?;

    let mut log_stream = docker.logs(
        &id,
        Some(LogsOptions::<String> {
            stdout: true,
            stderr: true,
            follow: false,
            ..Default::default()
        }),
    );
    let mut logs = String::new();
    while let Some(item) = log_stream.next().await {
        if append_log_item(&mut logs, item) {
            break;
        }
    }

    if req.auto_remove {
        let _ = docker
            .remove_container(
                &id,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await;
    }

    Ok(RunContainerResult {
        status_code,
        logs,
        container_id: id,
    })
}

async fn start_persistent_async(
    req: StartPersistentRequest,
) -> Result<PersistentContainer, ContainerError> {
    let docker = Docker::connect_with_local_defaults()
        .map_err(|e| ContainerError::msg(format!("connect docker: {e}")))?;

    let container_port = req.container_port.unwrap_or(3737);
    let mut port_bindings: Option<HashMap<String, Option<Vec<PortBinding>>>> = None;
    let mut exposed: Option<HashMap<String, HashMap<(), ()>>> = None;
    if req.host_port.is_some() || req.container_port.is_some() {
        let host = req.host_port.map(|p| p.to_string()).unwrap_or_default();
        let key = format!("{container_port}/tcp");
        let binding = PortBinding {
            host_ip: Some("127.0.0.1".into()),
            host_port: if host.is_empty() { None } else { Some(host) },
        };
        let mut map = HashMap::new();
        map.insert(key.clone(), Some(vec![binding]));
        port_bindings = Some(map);
        let mut exp = HashMap::new();
        exp.insert(key, HashMap::new());
        exposed = Some(exp);
    }

    let host_config = HostConfig {
        binds: Some(req.binds.clone()),
        port_bindings,
        auto_remove: Some(false),
        ..Default::default()
    };

    let config = Config {
        image: Some(req.image.clone()),
        cmd: Some(req.cmd.clone()),
        working_dir: req.workdir.clone(),
        env: if req.env.is_empty() {
            None
        } else {
            Some(req.env.clone())
        },
        host_config: Some(host_config),
        exposed_ports: exposed,
        tty: Some(false),
        open_stdin: Some(false),
        ..Default::default()
    };

    let opts = req.name.as_ref().map(|n| CreateContainerOptions {
        name: n.clone(),
        platform: None,
    });

    let created = docker
        .create_container(opts, config)
        .await
        .map_err(|e| ContainerError::msg(format!("create: {e}")))?;
    let id = created.id;

    docker
        .start_container(&id, None::<StartContainerOptions<String>>)
        .await
        .map_err(|e| ContainerError::msg(format!("start: {e}")))?;

    // Resolve published host port if Docker assigned one.
    let mut host_port = req.host_port;
    if host_port.is_none() {
        if let Ok(inspect) = docker.inspect_container(&id, None).await {
            if let Some(net) = inspect.network_settings {
                if let Some(ports) = net.ports {
                    let key = format!("{container_port}/tcp");
                    if let Some(Some(bindings)) = ports.get(&key) {
                        if let Some(b) = bindings.first() {
                            if let Some(hp) = &b.host_port {
                                host_port = hp.parse().ok();
                            }
                        }
                    }
                }
            }
        }
    }

    Ok(PersistentContainer {
        container_id: id,
        host_port,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::port::ContainerError;

    #[test]
    fn container_error_display() {
        assert_eq!(ContainerError::msg("x").to_string(), "x");
    }

    #[test]
    fn apply_wait_result_paths() {
        let mut code = -1;
        let mut err = None;
        assert!(!apply_wait_result(&mut code, &mut err, Ok(3)));
        assert_eq!(code, 3);
        assert!(apply_wait_result(
            &mut code,
            &mut err,
            Err("wait boom".into())
        ));
        assert_eq!(err.as_deref(), Some("wait boom"));
    }

    #[test]
    fn resolve_status_paths() {
        assert_eq!(resolve_status_code(0, None, None).unwrap(), 0);
        assert_eq!(resolve_status_code(-1, None, Some(7)).unwrap(), 7);
        let err = resolve_status_code(-1, Some("boom".into()), None).unwrap_err();
        assert!(err.to_string().contains("wait: boom"));
    }
}
