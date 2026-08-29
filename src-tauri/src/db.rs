/// db.rs
/// Handles SQLite connection initialization and schemas definition for local-first storage.

use rusqlite::{Connection, Result};
use std::path::Path;

pub fn init_db<P: AsRef<Path>>(path: P) -> Result<Connection> {
    let conn = Connection::open(path)?;

    // Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON;", [])?;

    // Create Section table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS Section (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            folderPath TEXT NOT NULL,
            orderIndex INTEGER NOT NULL,
            updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
        [],
    )?;

    // Create Page table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS Page (
            id TEXT PRIMARY KEY,
            sectionId TEXT NOT NULL,
            title TEXT NOT NULL,
            filePath TEXT NOT NULL,
            orderIndex INTEGER NOT NULL,
            isMissing INTEGER DEFAULT 0,
            updatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
        [],
    )?;

    // Create Block table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS Block (
            id TEXT PRIMARY KEY,
            pageId TEXT NOT NULL,
            type TEXT NOT NULL,
            orderIndex INTEGER NOT NULL,
            content TEXT NOT NULL
        );",
        [],
    )?;

    // Create Link table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS Link (
            id TEXT PRIMARY KEY,
            fromPageId TEXT NOT NULL,
            toPageId TEXT NOT NULL,
            fromNodeId TEXT,
            createdAt DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
        [],
    )?;

    // Create PageRecord table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS PageRecord (
            pageId TEXT PRIMARY KEY,
            status TEXT DEFAULT 'Todo',
            tags TEXT DEFAULT '[]',
            owner TEXT,
            dueDate TEXT
        );",
        [],
    )?;

    // Create PagePosition table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS PagePosition (
            pageId TEXT PRIMARY KEY,
            x REAL NOT NULL,
            y REAL NOT NULL
        );",
        [],
    )?;

    // Create PageSnapshot table
    conn.execute(
        "CREATE TABLE IF NOT EXISTS PageSnapshot (
            id TEXT PRIMARY KEY,
            pageId TEXT NOT NULL,
            title TEXT NOT NULL,
            blocks TEXT NOT NULL,
            createdAt DATETIME DEFAULT CURRENT_TIMESTAMP
        );",
        [],
    )?;

    Ok(conn)
}
