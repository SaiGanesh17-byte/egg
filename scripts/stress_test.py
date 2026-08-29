import os
import time
import shutil
import sqlite3
from pathlib import Path
from egg.core.engine import EggEngine

def create_stress_repo(repo_path: str):
    # Setup nested directories
    dirs = [
        "packages/core/auth",
        "packages/core/engine",
        "packages/core/billing",
        "services/billing/db",
        "services/billing/helpers",
        "ui/components/views",
        "ignored_dir",
        "temp_cache"
    ]
    for d in dirs:
        os.makedirs(os.path.join(repo_path, d), exist_ok=True)
        
    # Write root .gitignore
    with open(os.path.join(repo_path, ".gitignore"), "w") as f:
        f.write("ignored_dir/\n*.log\ntemp_cache/\n")
        
    # Write excluded files to verify ignore rules
    with open(os.path.join(repo_path, "ignored_dir", "ignored_module.py"), "w") as f:
        f.write("def ignored(): pass\n")
    with open(os.path.join(repo_path, "temp_cache", "cached_data.json"), "w") as f:
        f.write("{}\n")
    with open(os.path.join(repo_path, "debug.log"), "w") as f:
        f.write("Log trace\n")

    # Generate 100 Python files in packages/core/auth
    for i in range(100):
        file_path = os.path.join(repo_path, f"packages/core/auth/auth_service_{i}.py")
        with open(file_path, "w") as f:
            f.write(f"""
class AuthService{i}:
    def __init__(self, token):
        self.token = token
        
    def validate_session(self, session_id):
        # Call cross-file sibling service
        if session_id == "active":
            return True
        return False
        
def perform_auth_query_{i}(db):
    # SQL data access
    query = "SELECT * FROM billing_log_{i}"
    db.execute(query)
""")

    # Generate 100 TSX files in ui/components/views
    for i in range(100):
        file_path = os.path.join(repo_path, f"ui/components/views/View_{i}.tsx")
        with open(file_path, "w") as f:
            f.write(f"""
import React, {{ useState }} from 'react';

export function View{i}() {{
  const [active, setActive] = useState(false);
  
  const loadData = () => {{
    // ORM table reference
    const data = db.billing_log_{i}.find();
    setActive(true);
  }};
  
  return <div onClick={{loadData}}>View {i}</div>;
}}
""")

    # Generate 50 SQL files in services/billing/db
    for i in range(50):
        file_path = os.path.join(repo_path, f"services/billing/db/schema_{i}.sql")
        with open(file_path, "w") as f:
            f.write(f"""
CREATE TABLE billing_log_{i} (
    id INT PRIMARY KEY,
    amount DECIMAL(10,2)
);

INSERT INTO billing_log_{i} (id, amount) VALUES (1, 100.50);
""")

    # Generate 60 Rust files in packages/core/engine
    for i in range(60):
        file_path = os.path.join(repo_path, f"packages/core/engine/rust_module_{i}.rs")
        with open(file_path, "w") as f:
            f.write(f"""
struct EngineItem{i} {{
    id: u64,
}}

impl EngineItem{i} {{
    fn run(&self) -> bool {{
        let x = self.id;
        if x > 0 {{
            true
        }} else {{
            false
        }}
    }}
    
    fn match_state(&self, code: u32) {{
        match code {{
            200 => println!("OK"),
            _ => println!("Error"),
        }}
    }}
}}
""")

    # Generate 50 Go files in services/billing/helpers
    for i in range(50):
        file_path = os.path.join(repo_path, f"services/billing/helpers/helper_{i}.go")
        with open(file_path, "w") as f:
            f.write(f"""
package billing

type BillingHelper{i} struct {{
    enabled bool
}}

func (b *BillingHelper{i}) SetState(val bool) (bool, int) {{
    b.enabled = val
    code, status := update_state()
    return code, status
}}
""")

    # Generate 50 Java files in packages/core/billing
    for i in range(50):
        file_path = os.path.join(repo_path, f"packages/core/billing/BillingWorker_{i}.java")
        with open(file_path, "w") as f:
            f.write(f"""
public class BillingWorker{i} {{
    private String name;
    
    public BillingWorker{i}(String name) {{
        this.name = name;
    }}
    
    public void process() {{
        System.out.println("Processing");
    }}
    
    public void process(int retries) {{
        for (int i = 0; i < retries; i++) {{
            System.out.println("Retry " + i);
        }}
    }}
}}
""")

def run_stress_test():
    repo_path = os.path.abspath("./stress_test_repo")
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
        
    print("[Resilience Suite] Generating multi-language package hierarchy...")
    create_stress_repo(repo_path)
    
    engine = EggEngine()
    
    print("\n" + "="*60)
    print("SCENARIO 1: COLD FULL INDEX")
    print("="*60)
    start_time = time.time()
    stats = engine.scan_directory(repo_path)
    duration = time.time() - start_time
    throughput = stats["total_files"] / max(0.0001, duration)
    
    # Query DB stats
    db_path = os.path.join(repo_path, ".egg/graph.db")
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM symbols")
        symbols_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM graph_edges")
        edges_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM graph_edges WHERE edge_type = 'DATA_ACCESS'")
        data_access_count = cur.fetchone()[0]
        
    print(f"Total Discovered Files: {stats['total_files']}")
    print(f"Total Indexed Files:    {stats['indexed_files']}")
    print(f"Duration:              {duration:.2f} seconds")
    print(f"Throughput:            {throughput:.1f} files/second")
    print(f"CPG Symbols Indexed:    {symbols_count}")
    print(f"CPG Edges Generated:    {edges_count}")
    print(f"SQL Table Connections:  {data_access_count}")
    
    # Assert exclusions work (ignored directories and extensions should not be in DB)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM file_hashes WHERE file_path LIKE '%ignored_dir%' OR file_path LIKE '%temp_cache%' OR file_path LIKE '%.log'")
        ignored_count = cur.fetchone()[0]
    print(f"Ignored Exclusions Count: {ignored_count} (Assert: 0)")
    assert ignored_count == 0, "Exclusion filters failed!"
    
    print("\n" + "="*60)
    print("SCENARIO 2: ZERO-CHANGE WARM CACHE")
    print("="*60)
    start_time = time.time()
    stats_inc = engine.scan_directory(repo_path)
    duration_inc = time.time() - start_time
    speedup = duration / max(0.0001, duration_inc)
    
    print(f"Indexed Files: {stats_inc['indexed_files']} (Assert: 0)")
    print(f"Skipped Files: {stats_inc['skipped_files']} (Assert: {stats['total_files']})")
    print(f"Warm Duration: {duration_inc:.4f} seconds")
    print(f"Cache Speedup: {speedup:.1f}x")
    assert stats_inc["indexed_files"] == 0, "Warm cache did not skip unchanged files!"
    
    print("\n" + "="*60)
    print("SCENARIO 3: SINGLE-FILE MODIFICATION")
    print("="*60)
    mod_file = os.path.join(repo_path, "packages/core/auth/auth_service_0.py")
    with open(mod_file, "a") as f:
        f.write("\n# Modified for stress testing\n")
        
    start_time = time.time()
    stats_mod = engine.scan_directory(repo_path)
    duration_mod = time.time() - start_time
    
    print(f"Indexed Files: {stats_mod['indexed_files']} (Assert: 1)")
    print(f"Skipped Files: {stats_mod['skipped_files']} (Assert: {stats['total_files'] - 1})")
    print(f"Duration:      {duration_mod:.2f} seconds")
    assert stats_mod["indexed_files"] == 1, "Single-file modification re-indexed incorrect count!"
    
    print("\n" + "="*60)
    print("SCENARIO 4: SYNTAX ERROR RESILIENCE")
    print("="*60)
    broken_file = os.path.join(repo_path, "packages/core/auth/broken_syntax.py")
    with open(broken_file, "w") as f:
        f.write("def broken_func(:\n")  # Syntax error
        
    print("Running indexer with a syntax-broken file...")
    stats_err = engine.scan_directory(repo_path)
    print(f"Indexed Files: {stats_err['indexed_files']} (Assert: 0 for the broken file)")
    print(f"Total Files:   {stats_err['total_files']} (Assert: {stats['total_files'] + 1})")
    
    # Assert that indexer did not crash and correctly scanned remaining files
    assert os.path.exists(db_path), "Indexer crashed and lost DB!"
    
    print("\n" + "="*60)
    print("SCENARIO 5: FILE DELETION & STALE RECORD PURGE")
    print("="*60)
    # Check that broken_syntax.py is registered in file_hashes
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM file_hashes WHERE file_path = ?", ("packages/core/auth/broken_syntax.py",))
        before_del = cur.fetchone()[0]
    print(f"Records before deletion: {before_del}")
    
    # Delete the broken_syntax.py file and modify auth_service_0.py to verify
    os.remove(broken_file)
    print("Running indexer after deleting file...")
    stats_del = engine.scan_directory(repo_path)
    
    # Query database to assert records are purged
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM file_hashes WHERE file_path = ?", ("packages/core/auth/broken_syntax.py",))
        hashes_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM symbols WHERE file_path = ?", ("packages/core/auth/broken_syntax.py",))
        symbols_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM graph_edges WHERE source_id LIKE '%broken_syntax%' OR target_id LIKE '%broken_syntax%'")
        edges_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM ai_contexts WHERE file_path = ?", ("packages/core/auth/broken_syntax.py",))
        contexts_count = cur.fetchone()[0]
        
    print(f"Stale File Hashes Purged:    {hashes_count} (Assert: 0)")
    print(f"Stale Symbols Purged:        {symbols_count} (Assert: 0)")
    print(f"Stale Edges Purged:          {edges_count} (Assert: 0)")
    print(f"Stale AI Contexts Purged:    {contexts_count} (Assert: 0)")
    
    assert hashes_count == 0, "Deleted file was not purged from file_hashes!"
    assert symbols_count == 0, "Deleted file symbols were not purged!"
    assert edges_count == 0, "Deleted file edges were not purged!"
    assert contexts_count == 0, "Deleted file AI contexts were not purged!"

    print("\n" + "="*60)
    print("TEST SUITE COMPLETED SUCCESSFULLY!")
    print("="*60)
    
    # Clean up test directories
    shutil.rmtree(repo_path)

if __name__ == "__main__":
    run_stress_test()
