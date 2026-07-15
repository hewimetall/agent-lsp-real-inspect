//! Reconcile `containers(status=running)` against Docker Engine.
//!
//! Dead / missing containers are marked `stopped` and their session
//! `index_status` becomes `stale` so MCP clients must re-`ensure_runtime`.

use rusqlite::{params, Connection};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum WorkerError {
    #[error("{0}")]
    Message(String),
}

impl WorkerError {
    pub fn msg(s: impl Into<String>) -> Self {
        Self::Message(s.into())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunningBind {
    pub container_id: String,
    pub session_id: String,
    pub runtime_mode: String,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct ReconcileStats {
    pub checked: u64,
    pub marked_stale: u64,
    pub skipped_local: u64,
    pub inspect_errors: u64,
}

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Open sessions.db with the same pragmas as StateStore.
pub fn open_sessions_db(path: &Path) -> Result<Connection, WorkerError> {
    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent)
                .map_err(|e| WorkerError::msg(format!("create db dir: {e}")))?;
        }
    }
    let conn = Connection::open(path)
        .map_err(|e| WorkerError::msg(format!("sqlite open {}: {e}", path.display())))?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA busy_timeout=30000;
         PRAGMA foreign_keys=ON;",
    )
    .map_err(|e| WorkerError::msg(format!("pragma: {e}")))?;
    Ok(conn)
}

/// Rows that claim to be live Docker containers.
pub fn list_running_binds(conn: &Connection) -> Result<Vec<RunningBind>, WorkerError> {
    let mut stmt = conn
        .prepare(
            "SELECT container_id, session_id, runtime_mode
             FROM containers
             WHERE status = 'running'
             ORDER BY created_at ASC",
        )
        .map_err(|e| WorkerError::msg(format!("list_running prepare: {e}")))?;
    let rows = stmt
        .query_map([], |r| {
            Ok(RunningBind {
                container_id: r.get(0)?,
                session_id: r.get(1)?,
                runtime_mode: r.get(2)?,
            })
        })
        .map_err(|e| WorkerError::msg(format!("list_running query: {e}")))?;
    let mut out = Vec::new();
    for row in rows {
        out.push(row.map_err(|e| WorkerError::msg(format!("list_running row: {e}")))?);
    }
    Ok(out)
}

/// Mark container stopped and session index_status=`stale` in one transaction.
pub fn mark_runtime_stale(
    conn: &Connection,
    container_id: &str,
    session_id: &str,
) -> Result<(), WorkerError> {
    let ts = now_secs();
    let tx = conn
        .unchecked_transaction()
        .map_err(|e| WorkerError::msg(format!("tx begin: {e}")))?;
    tx.execute(
        "UPDATE containers SET status = 'stopped', updated_at = ?2
         WHERE container_id = ?1",
        params![container_id, ts],
    )
    .map_err(|e| WorkerError::msg(format!("mark container stopped: {e}")))?;
    // Only demote live index states — do not overwrite closed/error unnecessarily.
    tx.execute(
        "UPDATE sessions SET index_status = 'stale', updated_at = ?2
         WHERE session_id = ?1
           AND index_status IN ('ready', 'warming', 'cold')",
        params![session_id, ts],
    )
    .map_err(|e| WorkerError::msg(format!("mark session stale: {e}")))?;
    tx.commit()
        .map_err(|e| WorkerError::msg(format!("tx commit: {e}")))?;
    Ok(())
}

pub fn is_local_bind(bind: &RunningBind) -> bool {
    bind.runtime_mode == "local" || bind.container_id.starts_with("local-")
}

/// One reconcile pass. `is_running` returns Ok(false) for missing containers.
pub fn reconcile_once<F>(
    conn: &Connection,
    mut is_running: F,
) -> Result<ReconcileStats, WorkerError>
where
    F: FnMut(&str) -> Result<bool, WorkerError>,
{
    let mut stats = ReconcileStats::default();
    for bind in list_running_binds(conn)? {
        if is_local_bind(&bind) {
            stats.skipped_local += 1;
            continue;
        }
        stats.checked += 1;
        match is_running(&bind.container_id) {
            Ok(true) => {}
            Ok(false) => {
                mark_runtime_stale(conn, &bind.container_id, &bind.session_id)?;
                stats.marked_stale += 1;
            }
            Err(_) => {
                stats.inspect_errors += 1;
            }
        }
    }
    Ok(stats)
}

/// Resolve `$AGENT_LSP_STATE/sessions.db` (default `./state/sessions.db`).
pub fn sessions_db_path_from_env() -> std::path::PathBuf {
    let state = std::env::var("AGENT_LSP_STATE").unwrap_or_else(|_| "state".into());
    Path::new(&state).join("sessions.db")
}

pub fn poll_interval_secs_from_env() -> u64 {
    std::env::var("AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS")
        .ok()
        .and_then(|s| s.parse().ok())
        .filter(|&n| n > 0)
        .unwrap_or(15)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn setup_db() -> (tempfile::TempDir, Connection) {
        let dir = tempdir().unwrap();
        let path = dir.path().join("sessions.db");
        let conn = open_sessions_db(&path).unwrap();
        conn.execute_batch(
            "CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                active_workspace_id TEXT,
                meta TEXT,
                index_status TEXT NOT NULL DEFAULT 'cold',
                language TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE containers (
                container_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                image TEXT NOT NULL,
                language TEXT NOT NULL,
                host_port INTEGER,
                status TEXT NOT NULL DEFAULT 'running',
                runtime_mode TEXT NOT NULL DEFAULT 'container',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );",
        )
        .unwrap();
        (dir, conn)
    }

    fn insert_session(conn: &Connection, sid: &str, status: &str) {
        conn.execute(
            "INSERT INTO sessions(session_id, index_status, created_at, updated_at)
             VALUES (?1, ?2, 1, 1)",
            params![sid, status],
        )
        .unwrap();
    }

    fn insert_container(conn: &Connection, cid: &str, sid: &str, status: &str, mode: &str) {
        conn.execute(
            "INSERT INTO containers(
                container_id, session_id, image, language, status, runtime_mode,
                created_at, updated_at
             ) VALUES (?1, ?2, 'img', 'python', ?3, ?4, 1, 1)",
            params![cid, sid, status, mode],
        )
        .unwrap();
    }

    #[test]
    fn list_running_only() {
        let (_dir, conn) = setup_db();
        insert_session(&conn, "s1", "ready");
        insert_session(&conn, "s2", "ready");
        insert_container(&conn, "c1", "s1", "running", "container");
        insert_container(&conn, "c2", "s2", "stopped", "container");
        let binds = list_running_binds(&conn).unwrap();
        assert_eq!(binds.len(), 1);
        assert_eq!(binds[0].container_id, "c1");
    }

    #[test]
    fn mark_runtime_stale_updates_both() {
        let (_dir, conn) = setup_db();
        insert_session(&conn, "s1", "ready");
        insert_container(&conn, "c1", "s1", "running", "container");
        mark_runtime_stale(&conn, "c1", "s1").unwrap();
        let st: String = conn
            .query_row(
                "SELECT status FROM containers WHERE container_id='c1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(st, "stopped");
        let idx: String = conn
            .query_row(
                "SELECT index_status FROM sessions WHERE session_id='s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(idx, "stale");
    }

    #[test]
    fn mark_does_not_overwrite_closed() {
        let (_dir, conn) = setup_db();
        insert_session(&conn, "s1", "closed");
        insert_container(&conn, "c1", "s1", "running", "container");
        mark_runtime_stale(&conn, "c1", "s1").unwrap();
        let idx: String = conn
            .query_row(
                "SELECT index_status FROM sessions WHERE session_id='s1'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(idx, "closed");
    }

    #[test]
    fn reconcile_marks_dead_skips_local_and_alive() {
        let (_dir, conn) = setup_db();
        insert_session(&conn, "alive", "ready");
        insert_session(&conn, "dead", "ready");
        insert_session(&conn, "loc", "ready");
        insert_container(&conn, "cid-alive", "alive", "running", "container");
        insert_container(&conn, "cid-dead", "dead", "running", "container");
        insert_container(&conn, "local-1", "loc", "running", "local");

        let stats = reconcile_once(&conn, |id| Ok(id == "cid-alive")).unwrap();
        assert_eq!(stats.checked, 2);
        assert_eq!(stats.marked_stale, 1);
        assert_eq!(stats.skipped_local, 1);
        assert_eq!(stats.inspect_errors, 0);

        let dead_status: String = conn
            .query_row(
                "SELECT status FROM containers WHERE container_id='cid-dead'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(dead_status, "stopped");
        let dead_idx: String = conn
            .query_row(
                "SELECT index_status FROM sessions WHERE session_id='dead'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(dead_idx, "stale");

        let alive_status: String = conn
            .query_row(
                "SELECT status FROM containers WHERE container_id='cid-alive'",
                [],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(alive_status, "running");
    }

    #[test]
    fn reconcile_counts_inspect_errors() {
        let (_dir, conn) = setup_db();
        insert_session(&conn, "s1", "ready");
        insert_container(&conn, "c1", "s1", "running", "container");
        let stats = reconcile_once(&conn, |_| Err(WorkerError::msg("boom"))).unwrap();
        assert_eq!(stats.inspect_errors, 1);
        assert_eq!(stats.marked_stale, 0);
    }

    #[test]
    fn is_local_bind_variants() {
        assert!(is_local_bind(&RunningBind {
            container_id: "local-stdio-abc".into(),
            session_id: "s".into(),
            runtime_mode: "container".into(),
        }));
        assert!(is_local_bind(&RunningBind {
            container_id: "anything".into(),
            session_id: "s".into(),
            runtime_mode: "local".into(),
        }));
        assert!(!is_local_bind(&RunningBind {
            container_id: "abc123".into(),
            session_id: "s".into(),
            runtime_mode: "container".into(),
        }));
    }

    #[test]
    fn poll_interval_default_and_env() {
        assert_eq!(poll_interval_secs_from_env(), 15);
        std::env::set_var("AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS", "3");
        assert_eq!(poll_interval_secs_from_env(), 3);
        std::env::set_var("AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS", "0");
        assert_eq!(poll_interval_secs_from_env(), 15);
        std::env::remove_var("AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS");
    }

    #[test]
    fn sessions_db_path_default() {
        std::env::remove_var("AGENT_LSP_STATE");
        assert!(sessions_db_path_from_env()
            .to_string_lossy()
            .ends_with("state/sessions.db"));
        std::env::set_var("AGENT_LSP_STATE", "/var/lib/agent-lsp/state");
        assert_eq!(
            sessions_db_path_from_env(),
            Path::new("/var/lib/agent-lsp/state/sessions.db")
        );
        std::env::remove_var("AGENT_LSP_STATE");
    }
}
