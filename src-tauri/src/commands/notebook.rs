/// commands/notebook.rs
/// Implements Tauri commands for workspace loading, page prose reading, and saving.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;
use uuid::Uuid;
use rusqlite::{params, Connection};
use serde::Serialize;
use tauri::{AppHandle, State};

use crate::config::{load_config, save_config};
use crate::AppState;

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct PageInfo {
    pub id: String,
    pub sectionId: String,
    pub title: String,
    pub isMissing: bool,
    pub orderIndex: i32,
}

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct SectionInfo {
    pub id: String,
    pub name: String,
    pub orderIndex: i32,
    pub pages: Vec<PageInfo>,
}

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct NotebookInfo {
    pub workspacePath: String,
    pub sections: Vec<SectionInfo>,
    pub lastSessionClean: bool,
}

fn sanitize_name(name: &str) -> String {
    name.chars().map(|c| {
        match c {
            '/' | '\\' | '?' | '%' | '*' | ':' | '|' | '"' | '<' | '>' | ' ' | '\t' | '\r' | '\n' => '_',
            _ => c
        }
    }).collect()
}

struct PageProse {
    id: String,
    title: String,
    body: String,
}

/// Helper to parse YAML frontmatter from a Markdown file
fn parse_markdown(content: &str) -> Option<PageProse> {
    if !content.starts_with("---") {
        return None;
    }
    let parts: Vec<&str> = content.splitn(3, "---").collect();
    if parts.len() < 3 {
        return None;
    }
    let yaml = parts[1];
    let body = parts[2].trim().to_string();

    let mut id = None;
    let mut title = None;

    for line in yaml.lines() {
        let line = line.trim();
        if line.starts_with("id:") {
            id = Some(line.trim_start_matches("id:").trim().trim_matches('"').trim_matches('\'').to_string());
        } else if line.starts_with("title:") {
            title = Some(line.trim_start_matches("title:").trim().trim_matches('"').trim_matches('\'').to_string());
        }
    }

    match (id, title) {
        (Some(id), Some(title)) => Some(PageProse { id, title, body }),
        _ => None,
    }
}

/// Helper to write/format YAML frontmatter into a Markdown file
fn format_markdown(id: &str, title: &str, body: &str) -> String {
    format!("---\nid: \"{}\"\ntitle: \"{}\"\n---\n\n{}", id, title, body)
}

/// Open native folder picker to select a workspace directory
#[tauri::command]
pub fn select_workspace_dir(app: AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    let dialog = rfd::FileDialog::new()
        .set_title("Select NodeBook Workspace Directory");
    
    if let Some(path) = dialog.pick_folder() {
        let path_str = path.to_string_lossy().to_string();
        
        // Save to config
        let mut config = load_config(&app);
        config.workspace_path = Some(path_str.clone());
        save_config(&app, &config)?;

        // Update in-memory AppState base_workspace_path
        let mut base_guard = state.base_workspace_path.lock().map_err(|e| e.to_string())?;
        *base_guard = Some(path.clone());

        Ok(path_str)
    } else {
        Ok("CANCELLED".to_string())
    }
}

fn scan_notebook_dir(workspace_path: &std::path::Path) -> Result<Vec<SectionInfo>, String> {
    let db_path = workspace_path.join("notebook.db");
    let mut conn = crate::db::init_db(&db_path).map_err(|e| e.to_string())?;

    // Tracks processed UUIDs to resolve copy-paste duplicate collisions (first wins)
    let mut processed_uuids = HashSet::new();
    let mut found_page_ids = HashSet::new();
    let mut found_sections = HashMap::new(); // maps folder path to section ID

    // Read the directories to sync sections
    let entries = fs::read_dir(workspace_path).map_err(|e| e.to_string())?;
    let mut folders = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let dir_name = path.file_name().unwrap_or_default().to_string_lossy();
            if dir_name.starts_with('.') {
                continue;
            }
            folders.push(path);
        }
    }

    // Begin SQLite Transaction
    {
        let tx = conn.transaction().map_err(|e| e.to_string())?;

        // 1. Match directories to Sections
        for folder in &folders {
            let folder_name = folder.file_name().unwrap_or_default().to_string_lossy().to_string();
            let folder_path_str = folder.strip_prefix(workspace_path)
                .unwrap_or(folder)
                .to_string_lossy()
                .to_string();

            // Check if any page file in this directory matches an existing sectionId
            let mut resolved_section_id = None;
            
            // First check if the folderPath is already registered to a section in the database
            let mut folder_stmt = tx.prepare("SELECT id FROM Section WHERE folderPath = ? LIMIT 1").unwrap();
            if let Ok(sec_id) = folder_stmt.query_row(params![folder_path_str], |row| row.get::<_, String>(0)) {
                resolved_section_id = Some(sec_id);
            }

            if resolved_section_id.is_none() {
                if let Ok(files) = fs::read_dir(folder) {
                    for file_entry in files.flatten() {
                        let file_path = file_entry.path();
                        let file_name = file_path.file_name().unwrap_or_default().to_string_lossy();
                        if file_name.starts_with('.') {
                            continue;
                        }
                        if file_path.extension().map_or(false, |ext| ext == "md") {
                            if let Ok(content) = fs::read_to_string(&file_path) {
                                if let Some(parsed) = parse_markdown(&content) {
                                    if !processed_uuids.contains(&parsed.id) {
                                        let mut stmt = tx.prepare("SELECT sectionId FROM Page WHERE id = ? LIMIT 1").unwrap();
                                        if let Ok(sec_id) = stmt.query_row(params![parsed.id], |row| row.get::<_, String>(0)) {
                                            resolved_section_id = Some(sec_id);
                                            break;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            let section_id = match resolved_section_id {
                Some(sid) => {
                    tx.execute(
                        "UPDATE Section SET folderPath = ? WHERE id = ?",
                        params![folder_path_str, sid],
                    ).unwrap();
                    sid
                }
                None => {
                    let sid = Uuid::new_v4().to_string();
                    let count: i32 = tx.query_row("SELECT COUNT(*) FROM Section", [], |row| row.get(0)).unwrap_or(0);
                    tx.execute(
                        "INSERT INTO Section (id, name, folderPath, orderIndex) VALUES (?, ?, ?, ?)",
                        params![sid, folder_name, folder_path_str, count],
                    ).unwrap();
                    sid
                }
            };

            found_sections.insert(folder_path_str, section_id);
        }

        // 2. Parse Markdown files and synchronize Page tables
        for folder in &folders {
            let folder_path_str = folder.strip_prefix(workspace_path)
                .unwrap_or(folder)
                .to_string_lossy()
                .to_string();

            let section_id = found_sections.get(&folder_path_str).unwrap();

            if let Ok(files) = fs::read_dir(folder) {
                for file_entry in files.flatten() {
                    let f_path = file_entry.path();
                    let f_name = f_path.file_name().unwrap_or_default().to_string_lossy();
                    if f_name.starts_with('.') {
                        continue;
                    }
                    if f_path.extension().map_or(false, |ext| ext == "md") {
                        if let Ok(content) = fs::read_to_string(&f_path) {
                            if let Some(parsed) = parse_markdown(&content) {
                                if processed_uuids.contains(&parsed.id) {
                                    let new_uuid = Uuid::new_v4().to_string();
                                    let formatted_content = format_markdown(&new_uuid, &parsed.title, &parsed.body);
                                    let _ = fs::write(&f_path, formatted_content);
                                    
                                    let relative_path = f_path.strip_prefix(workspace_path)
                                        .unwrap_or(&f_path)
                                        .to_string_lossy()
                                        .to_string();

                                    let count: i32 = tx.query_row("SELECT COUNT(*) FROM Page WHERE sectionId = ?", params![section_id], |row| row.get(0)).unwrap_or(0);
                                    tx.execute(
                                        "INSERT INTO Page (id, sectionId, title, filePath, isMissing, orderIndex) VALUES (?, ?, ?, ?, 0, ?)",
                                        params![new_uuid, section_id, parsed.title, relative_path, count],
                                    ).unwrap();
                                    
                                    tx.execute(
                                        "INSERT OR IGNORE INTO PageRecord (pageId, status, tags, owner, dueDate) VALUES (?, 'Todo', '[]', NULL, NULL)",
                                        params![new_uuid],
                                    ).unwrap();

                                    processed_uuids.insert(new_uuid.clone());
                                    found_page_ids.insert(new_uuid);
                                } else {
                                    processed_uuids.insert(parsed.id.clone());
                                    found_page_ids.insert(parsed.id.clone());

                                    let relative_path = f_path.strip_prefix(workspace_path)
                                        .unwrap_or(&f_path)
                                        .to_string_lossy()
                                        .to_string();

                                    let exists: bool = tx.query_row(
                                        "SELECT EXISTS(SELECT 1 FROM Page WHERE id = ?)",
                                        params![parsed.id],
                                        |row| row.get(0),
                                    ).unwrap_or(false);

                                    if exists {
                                        tx.execute(
                                            "UPDATE Page SET title = ?, filePath = ?, sectionId = ?, isMissing = 0 WHERE id = ?",
                                            params![parsed.title, relative_path, section_id, parsed.id],
                                        ).unwrap();
                                    } else {
                                        let count: i32 = tx.query_row("SELECT COUNT(*) FROM Page WHERE sectionId = ?", params![section_id], |row| row.get(0)).unwrap_or(0);
                                        tx.execute(
                                            "INSERT INTO Page (id, sectionId, title, filePath, isMissing, orderIndex) VALUES (?, ?, ?, ?, 0, ?)",
                                            params![parsed.id, section_id, parsed.title, relative_path, count],
                                        ).unwrap();
                                    }

                                    tx.execute(
                                        "INSERT OR IGNORE INTO PageRecord (pageId, status, tags, owner, dueDate) VALUES (?, 'Todo', '[]', NULL, NULL)",
                                        params![parsed.id],
                                    ).unwrap();
                                }
                            }
                        }
                    }
                }
            }
        }

        // 3. Prune empty sections
        let mut check_stmt = tx.prepare("SELECT id, folderPath FROM Section").unwrap();
        let db_sections: Vec<(String, String)> = check_stmt.query_map([], |row| {
            Ok((row.get(0)?, row.get(1)?))
        }).unwrap().flatten().collect();
        drop(check_stmt);

        for (sec_id, folder_path_str) in db_sections {
            let section_folder = workspace_path.join(&folder_path_str);
            if !section_folder.exists() {
                let page_count: i32 = tx.query_row("SELECT COUNT(*) FROM Page WHERE sectionId = ?", params![sec_id], |row| row.get(0)).unwrap_or(0);
                if page_count == 0 {
                    let _ = tx.execute("DELETE FROM Section WHERE id = ?", params![sec_id]);
                }
            }
        }

        // 4. Mark missing pages
        tx.execute(
            "UPDATE Page SET isMissing = 1 WHERE id NOT IN (SELECT value FROM json_each(?))",
            params![serde_json::to_string(&found_page_ids.into_iter().collect::<Vec<String>>()).unwrap()],
        ).unwrap();

        tx.commit().map_err(|e| e.to_string())?;
    }

    // 5. Build hierarchy vectors
    let mut sections = Vec::new();
    let mut sect_stmt = conn.prepare("SELECT id, name, orderIndex FROM Section ORDER BY orderIndex ASC").unwrap();
    let sect_rows = sect_stmt.query_map([], |row| {
        Ok(SectionInfo {
            id: row.get(0)?,
            name: row.get(1)?,
            orderIndex: row.get(2)?,
            pages: Vec::new(),
        })
    }).unwrap();

    for mut sect in sect_rows.flatten() {
        let mut page_stmt = conn.prepare("SELECT id, title, isMissing, orderIndex FROM Page WHERE sectionId = ? ORDER BY orderIndex ASC").unwrap();
        let pages = page_stmt.query_map(params![sect.id], |row| {
            let is_missing_int: i32 = row.get(2)?;
            Ok(PageInfo {
                id: row.get(0)?,
                sectionId: sect.id.clone(),
                title: row.get(1)?,
                isMissing: is_missing_int == 1,
                orderIndex: row.get(3)?,
            })
        }).unwrap().flatten().collect();

        sect.pages = pages;
        sections.push(sect);
    }

    Ok(sections)
}

#[derive(Serialize)]
#[allow(non_snake_case)]
pub struct WorkspacePayload {
    pub baseWorkspacePath: String,
    pub notebooks: Vec<NotebookInfo>,
    pub lastSessionClean: bool,
}

#[tauri::command]
pub fn load_notebook(app: AppHandle, state: State<'_, AppState>) -> Result<WorkspacePayload, String> {
    let mut base_guard = state.base_workspace_path.lock().map_err(|e| e.to_string())?;
    
    // Check if workspace path is in AppState, fallback to configuration
    if base_guard.is_none() {
        let config = load_config(&app);
        if let Some(path_str) = config.workspace_path {
            let path = PathBuf::from(path_str);
            if path.exists() {
                *base_guard = Some(path);
            }
        }
    }

    let base_path = match &*base_guard {
        Some(p) => p.clone(),
        None => return Err("NO_WORKSPACE".to_string()),
    };

    let config = load_config(&app);
    let mut notebooks = Vec::new();

    let entries = fs::read_dir(&base_path).map_err(|e| e.to_string())?;
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let dir_name = path.file_name().unwrap_or_default().to_string_lossy();
            if dir_name.starts_with('.') {
                continue;
            }
            let sections = scan_notebook_dir(&path)?;
            notebooks.push(NotebookInfo {
                workspacePath: path.to_string_lossy().to_string(),
                sections,
                lastSessionClean: config.last_session_clean,
            });
        }
    }

    Ok(WorkspacePayload {
        baseWorkspacePath: base_path.to_string_lossy().to_string(),
        notebooks,
        lastSessionClean: config.last_session_clean,
    })
}

#[tauri::command]
pub fn select_active_notebook(path: String, state: State<'_, AppState>) -> Result<(), String> {
    let mut ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    *ws_guard = Some(PathBuf::from(path));
    Ok(())
}

#[tauri::command]
pub fn create_notebook(name: String, state: State<'_, AppState>) -> Result<String, String> {
    let base_guard = state.base_workspace_path.lock().map_err(|e| e.to_string())?;
    let base_path = base_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let sanitized_name = sanitize_name(&name);
    let notebook_dir = base_path.join(sanitized_name);

    if !notebook_dir.exists() {
        fs::create_dir_all(&notebook_dir).map_err(|e| e.to_string())?;
    }

    // Initialize the SQLite db inside it
    let db_path = notebook_dir.join("notebook.db");
    let _conn = crate::db::init_db(db_path).map_err(|e| e.to_string())?;

    Ok(notebook_dir.to_string_lossy().to_string())
}

#[tauri::command]
pub fn delete_notebook(path: String, delete_permanently: bool) -> Result<(), String> {
    let old_path = PathBuf::from(path);
    if old_path.exists() {
        if delete_permanently {
            if old_path.is_dir() {
                fs::remove_dir_all(old_path).map_err(|e| e.to_string())?;
            }
        } else {
            let parent_dir = old_path.parent().ok_or("INVALID_PATH")?;
            let folder_name = old_path.file_name().ok_or("INVALID_PATH")?.to_string_lossy();
            let new_name = format!(".{}", folder_name);
            let new_path = parent_dir.join(new_name);
            fs::rename(old_path, new_path).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

/// Reads the markdown body content and database blocks for a page ID
#[tauri::command]
pub fn load_page_content(page_id: String, state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    // Look up file path and isMissing in database
    let (file_path_str, title, is_missing): (String, String, i32) = conn.query_row(
        "SELECT filePath, title, isMissing FROM Page WHERE id = ? LIMIT 1",
        params![page_id],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    ).map_err(|_| "PAGE_NOT_FOUND".to_string())?;

    let file_path = workspace_path.join(file_path_str);
    
    // Read prose from file
    let prose_body = if file_path.exists() {
        let content = fs::read_to_string(&file_path).map_err(|e| e.to_string())?;
        parse_markdown(&content).map_or("".to_string(), |p| p.body)
    } else {
        "".to_string()
    };

    // Load blocks from database
    let mut stmt = conn.prepare("SELECT id, type, orderIndex, content FROM Block WHERE pageId = ? ORDER BY orderIndex ASC").unwrap();
    let block_rows = stmt.query_map(params![page_id], |row| {
        let b_id: String = row.get(0)?;
        let b_type: String = row.get(1)?;
        let b_order: i32 = row.get(2)?;
        let b_content_str: String = row.get(3)?;
        let b_content: serde_json::Value = serde_json::from_str(&b_content_str).unwrap_or(serde_json::Value::Null);

        Ok(serde_json::json!({
            "id": b_id,
            "pageId": page_id,
            "type": b_type,
            "orderIndex": b_order,
            "content": b_content
        }))
    }).unwrap().flatten().collect::<Vec<serde_json::Value>>();

    // Load page record metadata
    let record_data: serde_json::Value = conn.query_row(
        "SELECT status, tags, owner, dueDate FROM PageRecord WHERE pageId = ? LIMIT 1",
        params![page_id],
        |row| {
            let tags_str: String = row.get(1).unwrap_or("[]".to_string());
            let tags: serde_json::Value = serde_json::from_str(&tags_str).unwrap_or(serde_json::Value::Array(Vec::new()));
            Ok(serde_json::json!({
                "status": row.get::<_, String>(0).unwrap_or("Todo".to_string()),
                "tags": tags,
                "owner": row.get::<_, Option<String>>(2).unwrap(),
                "dueDate": row.get::<_, Option<String>>(3).unwrap()
            }))
        },
    ).unwrap_or(serde_json::json!({
        "status": "Todo",
        "tags": [],
        "owner": null,
        "dueDate": null
    }));

    Ok(serde_json::json!({
        "id": page_id,
        "title": title,
        "isMissing": is_missing == 1,
        "prose": prose_body,
        "blocks": block_rows,
        "record": record_data
    }))
}

/// Writes markdown content (frontmatter UUID + title + body) back to the page's file path
#[tauri::command]
pub fn save_page_content(page_id: String, markdown_content: String, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    // Look up file path and title in database
    let (file_path_str, title): (String, String) = conn.query_row(
        "SELECT filePath, title FROM Page WHERE id = ? LIMIT 1",
        params![page_id],
        |row| Ok((row.get(0).unwrap(), row.get(1).unwrap())),
    ).map_err(|_| "PAGE_NOT_FOUND".to_string())?;

    let file_path = workspace_path.join(file_path_str);

    // Format content with frontmatter
    let formatted = format_markdown(&page_id, &title, &markdown_content);

    // Ensure parent directory exists
    if let Some(parent) = file_path.parent() {
        let _ = fs::create_dir_all(parent);
    }

    // Write file
    fs::write(file_path, formatted).map_err(|e| e.to_string())?;

    // Update updatedAt in SQLite
    conn.execute(
        "UPDATE Page SET updatedAt = CURRENT_TIMESTAMP, isMissing = 0 WHERE id = ?",
        params![page_id],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub fn create_section(name: String, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let sanitized_name = sanitize_name(&name);
    let folder_path = workspace_path.join(&sanitized_name);

    if !folder_path.exists() {
        fs::create_dir_all(&folder_path).map_err(|e| e.to_string())?;
    }

    let section_id = Uuid::new_v4().to_string();
    let count: i32 = conn.query_row("SELECT COUNT(*) FROM Section", [], |row| row.get(0)).unwrap_or(0);

    conn.execute(
        "INSERT INTO Section (id, name, folderPath, orderIndex) VALUES (?, ?, ?, ?)",
        params![section_id, name, sanitized_name, count],
    ).map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub fn rename_section(section_id: String, new_name: String, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let old_folder_name: String = conn.query_row(
        "SELECT folderPath FROM Section WHERE id = ? LIMIT 1",
        params![section_id],
        |row| row.get(0),
    ).map_err(|_| "SECTION_NOT_FOUND")?;

    let sanitized_new_name = sanitize_name(&new_name);

    let old_path = workspace_path.join(&old_folder_name);
    let new_path = workspace_path.join(&sanitized_new_name);

    if old_path.exists() && old_path != new_path {
        fs::rename(old_path, &new_path).map_err(|e| e.to_string())?;
    }

    conn.execute(
        "UPDATE Section SET name = ?, folderPath = ? WHERE id = ?",
        params![new_name, sanitized_new_name, section_id],
    ).map_err(|e| e.to_string())?;

    // Also update all page filePaths in this section!
    let mut stmt = conn.prepare("SELECT id, filePath FROM Page WHERE sectionId = ?").unwrap();
    let pages: Vec<(String, String)> = stmt.query_map(params![section_id], |row| {
        Ok((row.get(0)?, row.get(1)?))
    }).unwrap().flatten().collect();

    for (p_id, old_file_path) in pages {
        let p_path = PathBuf::from(old_file_path);
        if let Some(file_name) = p_path.file_name() {
            let new_file_path = PathBuf::from(&sanitized_new_name).join(file_name).to_string_lossy().to_string();
            let _ = conn.execute("UPDATE Page SET filePath = ? WHERE id = ?", params![new_file_path, p_id]);
        }
    }

    Ok(())
}

#[tauri::command]
pub fn delete_section(section_id: String, delete_permanently: bool, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let mut conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let folder_name: String = conn.query_row(
        "SELECT folderPath FROM Section WHERE id = ? LIMIT 1",
        params![section_id],
        |row| row.get(0),
    ).map_err(|_| "SECTION_NOT_FOUND")?;

    let folder_path = workspace_path.join(folder_name);

    if folder_path.exists() {
        if delete_permanently {
            let _ = fs::remove_dir_all(&folder_path);
        } else {
            let parent_dir = folder_path.parent().ok_or("INVALID_PATH")?;
            let dir_name = folder_path.file_name().ok_or("INVALID_PATH")?.to_string_lossy();
            let new_name = format!(".{}", dir_name);
            let new_path = parent_dir.join(new_name);
            let _ = fs::rename(folder_path, new_path);
        }
    }

    let tx = conn.transaction().map_err(|e| e.to_string())?;
    tx.execute("DELETE FROM Block WHERE pageId IN (SELECT id FROM Page WHERE sectionId = ?)", params![section_id]).unwrap();
    tx.execute("DELETE FROM PageRecord WHERE pageId IN (SELECT id FROM Page WHERE sectionId = ?)", params![section_id]).unwrap();
    tx.execute("DELETE FROM PagePosition WHERE pageId IN (SELECT id FROM Page WHERE sectionId = ?)", params![section_id]).unwrap();
    tx.execute("DELETE FROM PageSnapshot WHERE pageId IN (SELECT id FROM Page WHERE sectionId = ?)", params![section_id]).unwrap();
    tx.execute("DELETE FROM Link WHERE fromPageId IN (SELECT id FROM Page WHERE sectionId = ?) OR toPageId IN (SELECT id FROM Page WHERE sectionId = ?)", params![section_id, section_id]).unwrap();
    tx.execute("DELETE FROM Page WHERE sectionId = ?", params![section_id]).unwrap();
    tx.execute("DELETE FROM Section WHERE id = ?", params![section_id]).unwrap();
    tx.commit().map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub fn create_page(title: String, section_id: String, state: State<'_, AppState>) -> Result<String, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let folder_name: String = conn.query_row(
        "SELECT folderPath FROM Section WHERE id = ? LIMIT 1",
        params![section_id],
        |row| row.get(0),
    ).map_err(|_| "SECTION_NOT_FOUND")?;

    let section_dir = workspace_path.join(&folder_name);
    let base_name = sanitize_name(&title);
    let mut file_name = format!("{}.md", base_name);
    let mut counter = 2;
    while section_dir.join(&file_name).exists() {
        file_name = format!("{}_{}.md", base_name, counter);
        counter += 1;
    }

    let file_path = section_dir.join(&file_name);
    let relative_file_path = PathBuf::from(&folder_name).join(&file_name).to_string_lossy().to_string();

    let page_id = Uuid::new_v4().to_string();
    let formatted_content = format_markdown(&page_id, &title, "");

    fs::write(file_path, formatted_content).map_err(|e| e.to_string())?;

    let count: i32 = conn.query_row("SELECT COUNT(*) FROM Page WHERE sectionId = ?", params![section_id], |row| row.get(0)).unwrap_or(0);

    conn.execute(
        "INSERT INTO Page (id, sectionId, title, filePath, orderIndex) VALUES (?, ?, ?, ?, ?)",
        params![page_id, section_id, title, relative_file_path, count],
    ).map_err(|e| e.to_string())?;

    Ok(page_id)
}

#[tauri::command]
pub fn rename_page(page_id: String, new_title: String, state: State<'_, AppState>) -> Result<String, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let (old_file_path_str, section_id): (String, String) = conn.query_row(
        "SELECT filePath, sectionId FROM Page WHERE id = ? LIMIT 1",
        params![page_id],
        |row| Ok((row.get(0).unwrap(), row.get(1).unwrap())),
    ).map_err(|_| "PAGE_NOT_FOUND")?;

    let folder_name: String = conn.query_row(
        "SELECT folderPath FROM Section WHERE id = ? LIMIT 1",
        params![section_id],
        |row| row.get(0),
    ).map_err(|_| "SECTION_NOT_FOUND")?;

    let section_dir = workspace_path.join(&folder_name);
    let base_name = sanitize_name(&new_title);
    let mut file_name = format!("{}.md", base_name);
    let mut counter = 2;
    while section_dir.join(&file_name).exists() {
        file_name = format!("{}_{}.md", base_name, counter);
        counter += 1;
    }

    let old_path = workspace_path.join(&old_file_path_str);
    let new_path = section_dir.join(&file_name);
    let relative_new_file_path = PathBuf::from(&folder_name).join(&file_name).to_string_lossy().to_string();

    // Read old content and update frontmatter title
    let old_content = if old_path.exists() {
        fs::read_to_string(&old_path).unwrap_or_default()
    } else {
        "".to_string()
    };

    let body = parse_markdown(&old_content).map_or("".to_string(), |p| p.body);
    let formatted_content = format_markdown(&page_id, &new_title, &body);

    fs::write(&new_path, formatted_content).map_err(|e| e.to_string())?;
    if old_path.exists() && old_path != new_path {
        let _ = fs::remove_file(old_path);
    }

    conn.execute(
        "UPDATE Page SET title = ?, filePath = ? WHERE id = ?",
        params![new_title, relative_new_file_path, page_id],
    ).map_err(|e| e.to_string())?;

    Ok(new_title)
}

#[tauri::command]
pub fn delete_page(page_id: String, delete_permanently: bool, state: State<'_, AppState>) -> Result<(), String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    let db_path = workspace_path.join("notebook.db");
    let mut conn = Connection::open(&db_path).map_err(|e| e.to_string())?;

    let file_path_str: String = conn.query_row(
        "SELECT filePath FROM Page WHERE id = ? LIMIT 1",
        params![page_id],
        |row| row.get(0),
    ).map_err(|_| "PAGE_NOT_FOUND")?;

    let file_path = workspace_path.join(file_path_str);
    if file_path.exists() {
        if delete_permanently {
            let _ = fs::remove_file(file_path);
        } else {
            let parent_dir = file_path.parent().ok_or("INVALID_PATH")?;
            let file_name = file_path.file_name().ok_or("INVALID_PATH")?.to_string_lossy();
            let new_name = format!(".{}", file_name);
            let new_path = parent_dir.join(new_name);
            let _ = fs::rename(file_path, new_path);
        }
    }

    let tx = conn.transaction().map_err(|e| e.to_string())?;
    tx.execute("DELETE FROM Block WHERE pageId = ?", params![page_id]).unwrap();
    tx.execute("DELETE FROM PageRecord WHERE pageId = ?", params![page_id]).unwrap();
    tx.execute("DELETE FROM PagePosition WHERE pageId = ?", params![page_id]).unwrap();
    tx.execute("DELETE FROM PageSnapshot WHERE pageId = ?", params![page_id]).unwrap();
    tx.execute("DELETE FROM Link WHERE fromPageId = ? OR toPageId = ?", params![page_id, page_id]).unwrap();
    tx.execute("DELETE FROM Page WHERE id = ?", params![page_id]).unwrap();
    tx.commit().map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub fn rename_notebook(path: String, new_name: String, state: State<'_, AppState>) -> Result<String, String> {
    let old_path = PathBuf::from(&path);
    let parent_dir = old_path.parent().ok_or("INVALID_PATH")?;
    let sanitized_new_name = sanitize_name(&new_name);
    let new_path = parent_dir.join(sanitized_new_name);

    if old_path.exists() && old_path != new_path {
        fs::rename(&old_path, &new_path).map_err(|e| e.to_string())?;
    }

    // If the active notebook workspace_path is old_path, update it to new_path
    let mut ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    if let Some(active_p) = &*ws_guard {
        if active_p == &old_path {
            *ws_guard = Some(new_path.clone());
        }
    }

    Ok(new_path.to_string_lossy().to_string())
}

#[tauri::command]
pub fn take_screen_clipping(state: State<'_, AppState>) -> Result<Option<String>, String> {
    let ws_guard = state.workspace_path.lock().map_err(|e| e.to_string())?;
    let workspace_path = ws_guard.as_ref().ok_or("NO_WORKSPACE")?;

    // Create a unique temporary filename inside the temp folder
    let temp_dir = std::env::temp_dir();
    let file_id = uuid::Uuid::new_v4().to_string();
    let temp_file = temp_dir.join(format!("clipping_{}.png", file_id));

    // Run macOS screencapture command in interactive selection mode
    let status = std::process::Command::new("screencapture")
        .arg("-i") // Interactive selection
        .arg(&temp_file)
        .status()
        .map_err(|e| format!("Failed to execute screencapture: {}", e))?;

    if !status.success() {
        return Ok(None); // User cancelled or it failed
    }

    if temp_file.exists() {
        // Copy to workspace's assets folder
        let assets_dir = workspace_path.join("assets");
        if !assets_dir.exists() {
            std::fs::create_dir_all(&assets_dir).map_err(|e| e.to_string())?;
        }
        
        let dest_filename = format!("{}.png", file_id);
        let dest_path = assets_dir.join(&dest_filename);
        std::fs::copy(&temp_file, &dest_path).map_err(|e| e.to_string())?;
        
        // Remove temp file
        let _ = std::fs::remove_file(temp_file);

        // Return relative path
        Ok(Some(format!("assets/{}", dest_filename)))
    } else {
        Ok(None)
    }
}
