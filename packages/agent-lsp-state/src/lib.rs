use parking_lot::Mutex;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use rusqlite::{params, Connection, OptionalExtension};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use uuid::Uuid;

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn open_db(path: &str) -> PyResult<Connection> {
    if let Some(parent) = Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            std::fs::create_dir_all(parent).map_err(|e| {
                PyValueError::new_err(format!("cannot create db dir {}: {e}", parent.display()))
            })?;
        }
    }
    let conn = Connection::open(path)
        .map_err(|e| PyValueError::new_err(format!("sqlite open {path}: {e}")))?;
    conn.execute_batch(
        "PRAGMA journal_mode=WAL;
         PRAGMA busy_timeout=30000;
         PRAGMA foreign_keys=ON;",
    )
    .map_err(|e| PyValueError::new_err(format!("pragma: {e}")))?;
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS workspaces (
            workspace_id TEXT PRIMARY KEY,
            project_id   TEXT NOT NULL,
            path         TEXT NOT NULL UNIQUE,
            ref_name     TEXT,
            status       TEXT NOT NULL DEFAULT 'active',
            created_at   INTEGER NOT NULL,
            updated_at   INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id          TEXT PRIMARY KEY,
            active_workspace_id TEXT,
            meta                TEXT,
            index_status        TEXT NOT NULL DEFAULT 'cold',
            language            TEXT,
            created_at          INTEGER NOT NULL,
            updated_at          INTEGER NOT NULL,
            FOREIGN KEY (active_workspace_id) REFERENCES workspaces(workspace_id)
        );
        CREATE TABLE IF NOT EXISTS containers (
            container_id   TEXT PRIMARY KEY,
            session_id     TEXT NOT NULL,
            image          TEXT NOT NULL,
            language       TEXT NOT NULL,
            host_port      INTEGER,
            status         TEXT NOT NULL DEFAULT 'running',
            runtime_mode   TEXT NOT NULL DEFAULT 'container',
            created_at     INTEGER NOT NULL,
            updated_at     INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );
        CREATE INDEX IF NOT EXISTS idx_workspaces_project
          ON workspaces(project_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_active_ws
          ON sessions(active_workspace_id);
        CREATE INDEX IF NOT EXISTS idx_containers_session
          ON containers(session_id);",
    )
    .map_err(|e| PyValueError::new_err(format!("schema: {e}")))?;
    // Migrations for DBs created before index_status/language columns.
    let _ = conn.execute(
        "ALTER TABLE sessions ADD COLUMN index_status TEXT NOT NULL DEFAULT 'cold'",
        [],
    );
    let _ = conn.execute("ALTER TABLE sessions ADD COLUMN language TEXT", []);
    Ok(conn)
}

/// Persistent sessions + workspaces + container bindings.
#[pyclass(name = "StateStore")]
struct StateStore {
    conn: Mutex<Connection>,
}

#[pymethods]
impl StateStore {
    #[new]
    fn new(path: &str) -> PyResult<Self> {
        Ok(Self {
            conn: Mutex::new(open_db(path)?),
        })
    }

    #[pyo3(signature = (meta=None))]
    fn create_session(&self, meta: Option<&str>) -> PyResult<String> {
        let sid = Uuid::new_v4().to_string();
        let ts = now_secs();
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO sessions(
                session_id, active_workspace_id, meta, index_status, language, created_at, updated_at
             ) VALUES (?1, NULL, ?2, 'cold', NULL, ?3, ?3)",
            params![sid, meta, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("create_session: {e}")))?;
        Ok(sid)
    }

    fn get_session<'py>(
        &self,
        py: Python<'py>,
        session_id: &str,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        let conn = self.conn.lock();
        let row = conn
            .query_row(
                "SELECT session_id, active_workspace_id, meta, index_status, language,
                        created_at, updated_at
                 FROM sessions WHERE session_id = ?1",
                params![session_id],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, Option<String>>(2)?,
                        r.get::<_, String>(3)?,
                        r.get::<_, Option<String>>(4)?,
                        r.get::<_, i64>(5)?,
                        r.get::<_, i64>(6)?,
                    ))
                },
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("get_session: {e}")))?;
        row.map(|t| session_to_dict(py, t)).transpose()
    }

    fn list_sessions<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let conn = self.conn.lock();
        let mut stmt = conn
            .prepare(
                "SELECT session_id, active_workspace_id, meta, index_status, language,
                        created_at, updated_at
                 FROM sessions ORDER BY created_at ASC",
            )
            .map_err(|e| PyValueError::new_err(format!("list_sessions: {e}")))?;
        let rows = stmt
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, Option<String>>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<String>>(4)?,
                    r.get::<_, i64>(5)?,
                    r.get::<_, i64>(6)?,
                ))
            })
            .map_err(|e| PyValueError::new_err(format!("list_sessions query: {e}")))?;

        let list = PyList::empty(py);
        for row in rows {
            let t = row.map_err(|e| PyValueError::new_err(format!("list_sessions row: {e}")))?;
            list.append(session_to_dict(py, t)?)?;
        }
        Ok(list)
    }

    fn set_index_status(&self, session_id: &str, status: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let n = conn
            .execute(
                "UPDATE sessions SET index_status = ?2, updated_at = ?3 WHERE session_id = ?1",
                params![session_id, status, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("set_index_status: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "session not found: {session_id}"
            )));
        }
        Ok(())
    }

    fn set_language(&self, session_id: &str, language: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let n = conn
            .execute(
                "UPDATE sessions SET language = ?2, updated_at = ?3 WHERE session_id = ?1",
                params![session_id, language, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("set_language: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "session not found: {session_id}"
            )));
        }
        Ok(())
    }

    #[pyo3(signature = (project_id, path, ref_name=None, workspace_id=None))]
    fn create_workspace(
        &self,
        project_id: &str,
        path: &str,
        ref_name: Option<&str>,
        workspace_id: Option<&str>,
    ) -> PyResult<String> {
        let wid = match workspace_id {
            Some(id) if !id.is_empty() => id.to_string(),
            _ => Uuid::new_v4().to_string(),
        };
        let ts = now_secs();
        let conn = self.conn.lock();
        conn.execute(
            "INSERT INTO workspaces(
                workspace_id, project_id, path, ref_name, status, created_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, 'active', ?5, ?5)",
            params![wid, project_id, path, ref_name, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("create_workspace: {e}")))?;
        Ok(wid)
    }

    fn get_workspace<'py>(
        &self,
        py: Python<'py>,
        workspace_id: &str,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        let conn = self.conn.lock();
        let row = conn
            .query_row(
                "SELECT workspace_id, project_id, path, ref_name, status, created_at, updated_at
                 FROM workspaces WHERE workspace_id = ?1",
                params![workspace_id],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, Option<String>>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, i64>(5)?,
                        r.get::<_, i64>(6)?,
                    ))
                },
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("get_workspace: {e}")))?;
        row.map(|t| workspace_to_dict(py, t)).transpose()
    }

    #[pyo3(signature = (project_id=None, status=None))]
    fn list_workspaces<'py>(
        &self,
        py: Python<'py>,
        project_id: Option<&str>,
        status: Option<&str>,
    ) -> PyResult<Bound<'py, PyList>> {
        let conn = self.conn.lock();
        let mut sql = String::from(
            "SELECT workspace_id, project_id, path, ref_name, status, created_at, updated_at
             FROM workspaces WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if let Some(p) = project_id {
            sql.push_str(" AND project_id = ?");
            binds.push(p.to_string());
        }
        if let Some(s) = status {
            sql.push_str(" AND status = ?");
            binds.push(s.to_string());
        }
        sql.push_str(" ORDER BY created_at ASC");

        let mut stmt = conn
            .prepare(&sql)
            .map_err(|e| PyValueError::new_err(format!("list_workspaces: {e}")))?;
        let param_refs: Vec<&dyn rusqlite::types::ToSql> = binds
            .iter()
            .map(|b| b as &dyn rusqlite::types::ToSql)
            .collect();
        let rows = stmt
            .query_map(param_refs.as_slice(), |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, Option<String>>(3)?,
                    r.get::<_, String>(4)?,
                    r.get::<_, i64>(5)?,
                    r.get::<_, i64>(6)?,
                ))
            })
            .map_err(|e| PyValueError::new_err(format!("list_workspaces query: {e}")))?;

        let list = PyList::empty(py);
        for row in rows {
            let t = row.map_err(|e| PyValueError::new_err(format!("list_workspaces row: {e}")))?;
            list.append(workspace_to_dict(py, t)?)?;
        }
        Ok(list)
    }

    fn set_active_workspace(&self, session_id: &str, workspace_id: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let exists: bool = conn
            .query_row(
                "SELECT 1 FROM workspaces WHERE workspace_id = ?1 AND status = 'active'",
                params![workspace_id],
                |_| Ok(true),
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("set_active_workspace ws: {e}")))?
            .unwrap_or(false);
        if !exists {
            return Err(PyValueError::new_err(format!(
                "active workspace not found: {workspace_id}"
            )));
        }
        let n = conn
            .execute(
                "UPDATE sessions SET active_workspace_id = ?2, updated_at = ?3
                 WHERE session_id = ?1",
                params![session_id, workspace_id, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("set_active_workspace: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "session not found: {session_id}"
            )));
        }
        Ok(())
    }

    fn mark_workspace_removed(&self, workspace_id: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let n = conn
            .execute(
                "UPDATE workspaces SET status = 'removed', updated_at = ?2
                 WHERE workspace_id = ?1",
                params![workspace_id, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("mark_workspace_removed: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "workspace not found: {workspace_id}"
            )));
        }
        conn.execute(
            "UPDATE sessions SET active_workspace_id = NULL, updated_at = ?2
             WHERE active_workspace_id = ?1",
            params![workspace_id, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("clear active: {e}")))?;
        Ok(())
    }

    /// Bind a container (or local runtime id) to a session.
    #[pyo3(signature = (session_id, container_id, image, language, host_port=None, runtime_mode="container"))]
    fn bind_container(
        &self,
        session_id: &str,
        container_id: &str,
        image: &str,
        language: &str,
        host_port: Option<i64>,
        runtime_mode: &str,
    ) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let exists: bool = conn
            .query_row(
                "SELECT 1 FROM sessions WHERE session_id = ?1",
                params![session_id],
                |_| Ok(true),
            )
            .optional()
            .map_err(|e| PyValueError::new_err(format!("bind_container session: {e}")))?
            .unwrap_or(false);
        if !exists {
            return Err(PyValueError::new_err(format!(
                "session not found: {session_id}"
            )));
        }
        conn.execute(
            "INSERT INTO containers(
                container_id, session_id, image, language, host_port, status,
                runtime_mode, created_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, 'running', ?6, ?7, ?7)
             ON CONFLICT(container_id) DO UPDATE SET
                status='running', host_port=excluded.host_port,
                image=excluded.image, language=excluded.language,
                runtime_mode=excluded.runtime_mode, updated_at=excluded.updated_at",
            params![
                container_id,
                session_id,
                image,
                language,
                host_port,
                runtime_mode,
                ts
            ],
        )
        .map_err(|e| PyValueError::new_err(format!("bind_container: {e}")))?;
        conn.execute(
            "UPDATE sessions SET language = ?2, updated_at = ?3 WHERE session_id = ?1",
            params![session_id, language, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("bind_container lang: {e}")))?;
        Ok(())
    }

    fn list_containers<'py>(
        &self,
        py: Python<'py>,
        session_id: &str,
    ) -> PyResult<Bound<'py, PyList>> {
        let conn = self.conn.lock();
        let mut stmt = conn
            .prepare(
                "SELECT container_id, session_id, image, language, host_port, status,
                        runtime_mode, created_at, updated_at
                 FROM containers WHERE session_id = ?1 ORDER BY created_at ASC",
            )
            .map_err(|e| PyValueError::new_err(format!("list_containers: {e}")))?;
        let rows = stmt
            .query_map(params![session_id], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, Option<i64>>(4)?,
                    r.get::<_, String>(5)?,
                    r.get::<_, String>(6)?,
                    r.get::<_, i64>(7)?,
                    r.get::<_, i64>(8)?,
                ))
            })
            .map_err(|e| PyValueError::new_err(format!("list_containers query: {e}")))?;
        let list = PyList::empty(py);
        for row in rows {
            let t = row.map_err(|e| PyValueError::new_err(format!("list_containers row: {e}")))?;
            list.append(container_to_dict(py, t)?)?;
        }
        Ok(list)
    }

    fn mark_container_stopped(&self, container_id: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        let n = conn
            .execute(
                "UPDATE containers SET status = 'stopped', updated_at = ?2
                 WHERE container_id = ?1",
                params![container_id, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("mark_container_stopped: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "container not found: {container_id}"
            )));
        }
        Ok(())
    }

    fn close_session(&self, session_id: &str) -> PyResult<()> {
        let ts = now_secs();
        let conn = self.conn.lock();
        conn.execute(
            "UPDATE containers SET status = 'stopped', updated_at = ?2 WHERE session_id = ?1",
            params![session_id, ts],
        )
        .map_err(|e| PyValueError::new_err(format!("close_session containers: {e}")))?;
        let n = conn
            .execute(
                "UPDATE sessions SET index_status = 'closed', active_workspace_id = NULL,
                        updated_at = ?2 WHERE session_id = ?1",
                params![session_id, ts],
            )
            .map_err(|e| PyValueError::new_err(format!("close_session: {e}")))?;
        if n == 0 {
            return Err(PyValueError::new_err(format!(
                "session not found: {session_id}"
            )));
        }
        Ok(())
    }
}

type SessionRow = (
    String,
    Option<String>,
    Option<String>,
    String,
    Option<String>,
    i64,
    i64,
);
type WorkspaceRow = (String, String, String, Option<String>, String, i64, i64);
type ContainerRow = (
    String,
    String,
    String,
    String,
    Option<i64>,
    String,
    String,
    i64,
    i64,
);

fn session_to_dict(py: Python<'_>, t: SessionRow) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("session_id", t.0)?;
    d.set_item("active_workspace_id", t.1)?;
    d.set_item("meta", t.2)?;
    d.set_item("index_status", t.3)?;
    d.set_item("language", t.4)?;
    d.set_item("created_at", t.5)?;
    d.set_item("updated_at", t.6)?;
    Ok(d)
}

fn workspace_to_dict(py: Python<'_>, t: WorkspaceRow) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("workspace_id", t.0)?;
    d.set_item("project_id", t.1)?;
    d.set_item("path", t.2)?;
    d.set_item("ref_name", t.3)?;
    d.set_item("status", t.4)?;
    d.set_item("created_at", t.5)?;
    d.set_item("updated_at", t.6)?;
    Ok(d)
}

fn container_to_dict(py: Python<'_>, t: ContainerRow) -> PyResult<Bound<'_, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("container_id", t.0)?;
    d.set_item("session_id", t.1)?;
    d.set_item("image", t.2)?;
    d.set_item("language", t.3)?;
    d.set_item("host_port", t.4)?;
    d.set_item("status", t.5)?;
    d.set_item("runtime_mode", t.6)?;
    d.set_item("created_at", t.7)?;
    d.set_item("updated_at", t.8)?;
    Ok(d)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<StateStore>()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyAnyMethods;
    use tempfile::tempdir;

    #[test]
    fn session_workspace_container_lifecycle() {
        let dir = tempdir().unwrap();
        let db = dir.path().join("sessions.db");
        Python::attach(|py| {
            let store = StateStore::new(db.to_str().unwrap()).unwrap();
            let sid = store.create_session(Some(r#"{"c":1}"#)).unwrap();
            let wid = store
                .create_workspace("p1", "/ws1", Some("main"), None)
                .unwrap();
            store.set_active_workspace(&sid, &wid).unwrap();
            store
                .bind_container(&sid, "c1", "agent-lsp/go:latest", "go", Some(3737), "container")
                .unwrap();
            store.set_index_status(&sid, "warming").unwrap();
            store.set_index_status(&sid, "ready").unwrap();
            let session = store.get_session(py, &sid).unwrap().unwrap();
            assert_eq!(
                session
                    .get_item("index_status")
                    .unwrap()
                    .unwrap()
                    .extract::<String>()
                    .unwrap(),
                "ready"
            );
            let containers = store.list_containers(py, &sid).unwrap();
            assert_eq!(containers.len(), 1);
            store.mark_container_stopped("c1").unwrap();
            store.close_session(&sid).unwrap();
            let session = store.get_session(py, &sid).unwrap().unwrap();
            assert_eq!(
                session
                    .get_item("index_status")
                    .unwrap()
                    .unwrap()
                    .extract::<String>()
                    .unwrap(),
                "closed"
            );
        });
    }

    #[test]
    fn now_secs_ok() {
        assert!(now_secs() >= 0);
    }
}
