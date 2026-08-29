/// commands/blocks.rs
/// Implements Tauri commands for blocks management (upserting, deleting, and table renames with validation).

use rusqlite::params;
use serde_json::Value;
use tauri::State;
use crate::AppState;

/// Upsert a block's structured content in the SQLite database
#[tauri::command]
pub fn save_block_data(
    page_id: String,
    block_id: String,
    block_type: String,
    content: Value,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    let content_str = serde_json::to_string(&content).map_err(|e| e.to_string())?;

    conn.execute(
        "INSERT INTO Block (id, pageId, type, orderIndex, content)
         VALUES (?1, ?2, ?3, (SELECT COALESCE(MAX(orderIndex)+1, 0) FROM Block WHERE pageId = ?2), ?4)
         ON CONFLICT(id) DO UPDATE SET content = ?4",
        params![block_id, page_id, block_type, content_str],
    ).map_err(|e| e.to_string())?;

    // Also update updatedAt on the parent page
    conn.execute(
        "UPDATE Page SET updatedAt = CURRENT_TIMESTAMP WHERE id = ?",
        params![page_id],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

/// Delete a block from the SQLite database
#[tauri::command]
pub fn delete_block(block_id: String, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    // Get the pageId before deleting to update its timestamp
    let page_id: Option<String> = conn.query_row(
        "SELECT pageId FROM Block WHERE id = ? LIMIT 1",
        params![block_id],
        |row| row.get(0),
    ).ok();

    conn.execute(
        "DELETE FROM Block WHERE id = ?",
        params![block_id],
    ).map_err(|e| e.to_string())?;

    if let Some(p_id) = page_id {
        conn.execute(
            "UPDATE Page SET updatedAt = CURRENT_TIMESTAMP WHERE id = ?",
            params![p_id],
        ).map_err(|e| e.to_string())?;
    }

    Ok(())
}

/// Renames a table block's visual name after verifying same-page name uniqueness
#[tauri::command]
pub fn update_table_block_name(
    block_id: String,
    new_name: String,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = rusqlite::Connection::open(&db_path).map_err(|e| e.to_string())?;

    // 1. Get the block's current details and parent pageId
    let (page_id, current_content_str): (String, String) = conn.query_row(
        "SELECT pageId, content FROM Block WHERE id = ? LIMIT 1",
        params![block_id],
        |row| Ok((row.get(0).unwrap(), row.get(1).unwrap())),
    ).map_err(|_| "BLOCK_NOT_FOUND".to_string())?;

    // 2. Fetch all other TABLE blocks on the same page and check name uniqueness
    let mut stmt = conn.prepare("SELECT id, content FROM Block WHERE pageId = ? AND type = 'TABLE' AND id != ?").unwrap();
    let other_tables = stmt.query_map(params![page_id, block_id], |row| {
        let id: String = row.get(0)?;
        let content_str: String = row.get(1)?;
        Ok((id, content_str))
    }).unwrap().flatten().collect::<Vec<(String, String)>>();

    for (_, content_str) in other_tables {
        if let Ok(json) = serde_json::from_str::<Value>(&content_str) {
            if let Some(name) = json.get("name").and_then(|n| n.as_str()) {
                if name.trim().eq_ignore_ascii_case(new_name.trim()) {
                    return Err("TABLE_NAME_COLLISION".to_string());
                }
            }
        }
    }

    // 3. Update the table name inside the block's content JSON
    let mut block_json: Value = serde_json::from_str(&current_content_str)
        .map_err(|e| format!("Corrupt block JSON: {}", e))?;
    
    if let Some(obj) = block_json.as_object_mut() {
        obj.insert("name".to_string(), Value::String(new_name));
    } else {
        return Err("BLOCK_CONTENT_NOT_OBJECT".to_string());
    }

    let updated_content_str = serde_json::to_string(&block_json).map_err(|e| e.to_string())?;

    // 4. Persist to SQLite
    conn.execute(
        "UPDATE Block SET content = ? WHERE id = ?",
        params![updated_content_str, block_id],
    ).map_err(|e| e.to_string())?;

    // 5. Update updatedAt on the page
    conn.execute(
        "UPDATE Page SET updatedAt = CURRENT_TIMESTAMP WHERE id = ?",
        params![page_id],
    ).map_err(|e| e.to_string())?;

    // Return the updated block content
    Ok(block_json)
}
