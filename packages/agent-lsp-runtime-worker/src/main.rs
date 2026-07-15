//! Background reconciler: dead Docker containers → SQLite `stale`.
//!
//! Env:
//! - `AGENT_LSP_STATE` — state dir (default `state`); DB is `$AGENT_LSP_STATE/sessions.db`
//! - `AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS` — poll interval (default 15)
//! - `RUST_LOG` — tracing filter (default `info`)

use agent_lsp_runtime_worker::{
    open_sessions_db, poll_interval_secs_from_env, reconcile_once, sessions_db_path_from_env,
    WorkerError,
};
use bollard::Docker;
use std::time::Duration;
use tracing::{error, info, warn};

async fn docker_is_running(docker: &Docker, container_id: &str) -> Result<bool, WorkerError> {
    match docker.inspect_container(container_id, None).await {
        Ok(inspect) => Ok(inspect
            .state
            .as_ref()
            .and_then(|s| s.running)
            .unwrap_or(false)),
        Err(e) => {
            let msg = e.to_string();
            if msg.contains("No such container") || msg.contains("404") {
                Ok(false)
            } else {
                Err(WorkerError::msg(format!("inspect {container_id}: {msg}")))
            }
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let db_path = sessions_db_path_from_env();
    let interval = poll_interval_secs_from_env();
    info!(
        db = %db_path.display(),
        interval_secs = interval,
        "agent-lsp-runtime-worker starting"
    );

    let docker =
        Docker::connect_with_local_defaults().map_err(|e| format!("connect docker: {e}"))?;

    let mut tick = tokio::time::interval(Duration::from_secs(interval));
    loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                info!("shutdown signal");
                break;
            }
            _ = tick.tick() => {
                let conn = match open_sessions_db(&db_path) {
                    Ok(c) => c,
                    Err(e) => {
                        warn!(error = %e, "open sessions.db");
                        continue;
                    }
                };
                // Collect ids first — SQLite Connection is Sync but we await Docker.
                let binds = match agent_lsp_runtime_worker::list_running_binds(&conn) {
                    Ok(b) => b,
                    Err(e) => {
                        warn!(error = %e, "list running binds");
                        continue;
                    }
                };
                // Pre-resolve running flags so reconcile_once stays sync + testable.
                let mut running_map = std::collections::HashMap::new();
                for bind in &binds {
                    if agent_lsp_runtime_worker::is_local_bind(bind) {
                        continue;
                    }
                    match docker_is_running(&docker, &bind.container_id).await {
                        Ok(alive) => {
                            running_map.insert(bind.container_id.clone(), Ok(alive));
                        }
                        Err(e) => {
                            warn!(
                                container_id = %bind.container_id,
                                error = %e,
                                "inspect failed"
                            );
                            running_map.insert(bind.container_id.clone(), Err(e));
                        }
                    }
                }
                match reconcile_once(&conn, |id| {
                    match running_map.get(id) {
                        Some(Ok(v)) => Ok(*v),
                        Some(Err(e)) => Err(WorkerError::msg(e.to_string())),
                        None => Ok(true), // local / skipped
                    }
                }) {
                    Ok(stats) => {
                        if stats.marked_stale > 0 || stats.inspect_errors > 0 {
                            info!(
                                checked = stats.checked,
                                marked_stale = stats.marked_stale,
                                skipped_local = stats.skipped_local,
                                inspect_errors = stats.inspect_errors,
                                "reconcile pass"
                            );
                        }
                    }
                    Err(e) => error!(error = %e, "reconcile failed"),
                }
            }
        }
    }
    Ok(())
}
