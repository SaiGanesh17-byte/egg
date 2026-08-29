/// commands/page_metadata.rs
/// Implements Tauri commands for CRM records, coordinates, and version snapshot histories.

use rusqlite::params;
use serde::Serialize;
use serde_json::Value;
use tauri::State;
use uuid::Uuid;
use crate::AppState;

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct SnapshotInfo {
    pub id: String,
    pub pageId: String,
    pub title: String,
    pub blocks: Value,
    pub createdAt: String,
}

/// Upserts CRM record fields (status, tags, owner, dueDate) for a page
#[tauri::command]
pub fn update_page_record(
    page_id: String,
    status: String,
    tags: Value,
    owner: Option<String>,
    due_date: Option<String>,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let tags_str = serde_json::to_string(&tags).map_err(|e| e.to_string())?;

    conn.execute(
        "INSERT INTO PageRecord (pageId, status, tags, owner, dueDate)
         VALUES (?1, ?2, ?3, ?4, ?5)
         ON CONFLICT(pageId) DO UPDATE SET status=?2, tags=?3, owner=?4, dueDate=?5",
        params![page_id, status, tags_str, owner, due_date],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

/// Upserts visual node coordinates for the global graph view
#[tauri::command]
pub fn update_page_position(
    page_id: String,
    x: f64,
    y: f64,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    conn.execute(
        "INSERT INTO PagePosition (pageId, x, y)
         VALUES (?1, ?2, ?3)
         ON CONFLICT(pageId) DO UPDATE SET x=?2, y=?3",
        params![page_id, x, y],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

/// Fetches the last 20 snapshots recorded for a page
#[tauri::command]
pub fn load_page_snapshots(page_id: String, state: State<'_, AppState>) -> Result<Vec<SnapshotInfo>, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let mut stmt = conn.prepare(
        "SELECT id, pageId, title, blocks, createdAt
         FROM PageSnapshot
         WHERE pageId = ?
         ORDER BY createdAt DESC LIMIT 20"
    ).unwrap();

    let snapshots = stmt.query_map(params![page_id], |row| {
        let blocks_str: String = row.get(3)?;
        let blocks: Value = serde_json::from_str(&blocks_str).unwrap_or(Value::Array(Vec::new()));
        Ok(SnapshotInfo {
            id: row.get(0)?,
            pageId: row.get(1)?,
            title: row.get(2)?,
            blocks,
            createdAt: row.get(4)?,
        })
    }).unwrap().flatten().collect::<Vec<SnapshotInfo>>();

    Ok(snapshots)
}

/// Creates a new page snapshot, and auto-prunes snapshots beyond the newest 20
#[tauri::command]
pub fn create_page_snapshot(
    page_id: String,
    title: String,
    blocks: Value,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let blocks_str = serde_json::to_string(&blocks).map_err(|e| e.to_string())?;
    let snapshot_id = Uuid::new_v4().to_string();

    // Insert snapshot
    conn.execute(
        "INSERT INTO PageSnapshot (id, pageId, title, blocks) VALUES (?, ?, ?, ?)",
        params![snapshot_id, page_id, title, blocks_str],
    ).map_err(|e| e.to_string())?;

    // Prune older snapshots keeping only latest 20
    conn.execute(
        "DELETE FROM PageSnapshot
         WHERE pageId = ? AND id NOT IN (
             SELECT id FROM PageSnapshot
             WHERE pageId = ?
             ORDER BY createdAt DESC LIMIT 20
         )",
        params![page_id, page_id],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

/// Restores page blocks and details from a specific snapshot record
#[tauri::command]
pub fn restore_page_snapshot(
    page_id: String,
    snapshot_id: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let mut conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    // Load target snapshot blocks content
    let blocks_str: String = conn.query_row(
        "SELECT blocks FROM PageSnapshot WHERE id = ? AND pageId = ? LIMIT 1",
        params![snapshot_id, page_id],
        |row| row.get(0),
    ).map_err(|_| "SNAPSHOT_NOT_FOUND".to_string())?;

    let blocks: Vec<Value> = serde_json::from_str(&blocks_str)
        .map_err(|e| format!("Corrupted snapshot data: {}", e))?;

    // Transaction
    let tx = conn.transaction().map_err(|e| e.to_string())?;

    // Delete existing blocks
    tx.execute("DELETE FROM Block WHERE pageId = ?", params![page_id]).unwrap();

    // Insert snapshot blocks
    for (idx, block) in blocks.iter().enumerate() {
        let b_id = block.get("id").and_then(|id| id.as_str()).map(|s| s.to_string())
            .unwrap_or_else(|| Uuid::new_v4().to_string());
        let b_type = block.get("type").and_then(|t| t.as_str()).unwrap_or("TEXT").to_string();
        let b_content = block.get("content").cloned().unwrap_or(Value::Null);
        let b_content_str = serde_json::to_string(&b_content).unwrap_or_default();

        tx.execute(
            "INSERT INTO Block (id, pageId, type, orderIndex, content) VALUES (?, ?, ?, ?, ?)",
            params![b_id, page_id, b_type, idx as i32, b_content_str],
        ).unwrap();
    }

    tx.commit().map_err(|e| e.to_string())?;

    Ok(())
}
