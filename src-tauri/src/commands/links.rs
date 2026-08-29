/// commands/links.rs
/// Implements Tauri commands for managing backlinks and connections.

use rusqlite::params;
use serde::Serialize;
use tauri::State;
use uuid::Uuid;
use crate::AppState;

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct BacklinkInfo {
    pub linkId: String,
    pub pageId: String,
    pub title: String,
}

/// Retrieve pages that link to the specified target page ID
#[tauri::command]
pub fn get_backlinks(page_id: String, state: State<'_, AppState>) -> Result<Vec<BacklinkInfo>, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let mut stmt = conn.prepare(
        "SELECT l.id, p.id, p.title
         FROM Link l
         JOIN Page p ON l.fromPageId = p.id
         WHERE l.toPageId = ? AND p.isMissing = 0"
    ).unwrap();

    let backlinks = stmt.query_map(params![page_id], |row| {
        Ok(BacklinkInfo {
            linkId: row.get(0)?,
            pageId: row.get(1)?,
            title: row.get(2)?,
        })
    }).unwrap().flatten().collect::<Vec<BacklinkInfo>>();

    Ok(backlinks)
}

/// Create a new connection link between two pages
#[tauri::command]
pub fn create_link(
    from_page_id: String,
    to_page_id: String,
    from_node_id: Option<String>,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let link_id = Uuid::new_v4().to_string();

    conn.execute(
        "INSERT INTO Link (id, fromPageId, toPageId, fromNodeId) VALUES (?, ?, ?, ?)",
        params![link_id, from_page_id, to_page_id, from_node_id],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

/// Delete a page connection link
#[tauri::command]
pub fn delete_link(link_id: String, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    conn.execute(
        "DELETE FROM Link WHERE id = ?",
        params![link_id],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct LinkInfo {
    pub id: String,
    pub fromPageId: String,
    pub toPageId: String,
    pub fromNodeId: Option<String>,
}

#[tauri::command]
pub fn get_all_links(state: State<'_, AppState>) -> Result<Vec<LinkInfo>, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let mut stmt = conn.prepare("SELECT id, fromPageId, toPageId, fromNodeId FROM Link").unwrap();
    let links = stmt.query_map([], |row| {
        Ok(LinkInfo {
            id: row.get(0)?,
            fromPageId: row.get(1)?,
            toPageId: row.get(2)?,
            fromNodeId: row.get(3)?,
        })
    }).unwrap().flatten().collect::<Vec<LinkInfo>>();

    Ok(links)
}
