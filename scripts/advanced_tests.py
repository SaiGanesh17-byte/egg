import os
import time
import shutil
import sqlite3
import threading
from pathlib import Path
from egg.core.engine import EggEngine
from egg.core.tree_builder import generate_tree

def setup_complex_repo(repo_path: str):
    os.makedirs(repo_path, exist_ok=True)
    
    # 1. Define SQL Schema with multiple tables
    os.makedirs(os.path.join(repo_path, "db"), exist_ok=True)
    with open(os.path.join(repo_path, "db/schema.sql"), "w") as f:
        f.write("""
        CREATE TABLE accounts (
            id INT PRIMARY KEY,
            email VARCHAR(255)
        );
        CREATE TABLE transactions (
            id INT PRIMARY KEY,
            account_id INT,
            amount DECIMAL(10,2)
        );
        CREATE TABLE logs (
            id INT PRIMARY KEY,
            message TEXT
        );
        """)

    # 2. Python service with multiline queries and complex JOINs referencing multiple tables
    os.makedirs(os.path.join(repo_path, "services"), exist_ok=True)
    with open(os.path.join(repo_path, "services/billing.py"), "w") as f:
        f.write("""
def process_billing(db, account_id):
    # Multi-line string query with JOIN referencing 'accounts' and 'transactions'
    query = \"\"\"
        SELECT accounts.email, SUM(transactions.amount) as total
        FROM accounts
        INNER JOIN transactions ON accounts.id = transactions.account_id
        WHERE accounts.id = %s
        GROUP BY accounts.email
    \"\"\"
    db.execute(query, (account_id,))
    
    # Another query referencing 'logs'
    log_query = "INSERT INTO logs (message) VALUES ('Billing processed')"
    db.execute(log_query)
""")

    # 3. TSX component using backtick multi-line templates and multiple JOINs
    os.makedirs(os.path.join(repo_path, "ui"), exist_ok=True)
    with open(os.path.join(repo_path, "ui/Dashboard.tsx"), "w") as f:
        f.write("""
export function Dashboard({ db, accountId }) {
  const fetchStats = () => {
    // Multi-line backtick template referencing accounts and transactions
    const sql = `
      SELECT a.email, t.amount
      FROM accounts a
      LEFT JOIN transactions t ON a.id = t.account_id
      WHERE a.id = ${accountId}
    `;
    return db.query(sql);
  };
}
""")

    # 4. Deeply nested packages to test tree generation sorting
    nested_path = os.path.join(repo_path, "packages/a/b/c/d/e")
    os.makedirs(nested_path, exist_ok=True)
    with open(os.path.join(nested_path, "deep.py"), "w") as f:
        f.write("def deep_func(): pass\n")
    # File in sibling directory
    sibling_path = os.path.join(repo_path, "packages/a/b/sibling")
    os.makedirs(sibling_path, exist_ok=True)
    with open(os.path.join(sibling_path, "helper.py"), "w") as f:
        f.write("def help(): pass\n")

def run_advanced_tests():
    repo_path = os.path.abspath("./advanced_test_repo")
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
        
    print("[Advanced Test] Setting up test repository...")
    setup_complex_repo(repo_path)
    
    engine = EggEngine()
    
    # -------------------------------------------------------------
    # PART 1: Complex Multi-Line SQL Query Testing
    # -------------------------------------------------------------
    print("\n" + "="*60)
    print("TEST PART 1: MULTI-LINE SQL QUERY & COMPLEX JOIN RESOLUTION")
    print("="*60)
    
    engine.scan_directory(repo_path)
    
    db_path = os.path.join(repo_path, ".egg/graph.db")
    edges = []
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT source_id, target_id, edge_type, label 
            FROM graph_edges 
            WHERE edge_type = 'DATA_ACCESS'
            ORDER BY source_id, target_id
        """)
        edges = cur.fetchall()
        
    print("Resolved SQL Data Access Edges:")
    for src, tgt, etype, lbl in edges:
        print(f" - {src} -> {tgt} ({etype})")
        
    # Assertions
    # 1. Dashboard (TSX) should access accounts and transactions
    # 2. process_billing (Python) should access accounts, transactions, and logs
    targets_for_billing = [e[1] for e in edges if "process_billing" in e[0]]
    targets_for_dashboard = [e[1] for e in edges if "Dashboard" in e[0]]
    
    assert "SQL::TABLE.accounts" in targets_for_billing, "process_billing failed to link to accounts!"
    assert "SQL::TABLE.transactions" in targets_for_billing, "process_billing failed to link to transactions!"
    assert "SQL::TABLE.logs" in targets_for_billing, "process_billing failed to link to logs!"
    
    assert "SQL::TABLE.accounts" in targets_for_dashboard, "Dashboard failed to link to accounts!"
    assert "SQL::TABLE.transactions" in targets_for_dashboard, "Dashboard failed to link to transactions!"
    
    print("\nPart 1 Assertions Passed! Multi-line queries, backticks, and JOINs resolved correctly.")
    
    # -------------------------------------------------------------
    # PART 2: SQLite WAL Mode Concurrency Stress Test
    # -------------------------------------------------------------
    print("\n" + "="*60)
    print("TEST PART 2: SQLITE CONCURRENT SCANNING & WAL MODE RESILIENCE")
    print("="*60)
    
    # We will trigger 5 concurrent scanning threads reading/writing the same DB
    threads = []
    errors = []
    
    def worker_scan(thread_idx):
        try:
            # Force write locks by adding a unique file per thread
            thread_file = os.path.join(repo_path, f"services/thread_{thread_idx}.py")
            with open(thread_file, "w") as f:
                f.write(f"def thread_func_{thread_idx}(): pass\n")
            
            # Run scan
            engine.scan_directory(repo_path)
            # Cleanup thread file
            os.remove(thread_file)
        except Exception as e:
            errors.append(e)

    print("Launching 5 concurrent indexer threads...")
    for i in range(5):
        t = threading.Thread(target=worker_scan, args=(i,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    print(f"Concurrency run complete. Active Errors: {len(errors)}")
    for err in errors:
        print(f" - Error: {err}")
        
    assert len(errors) == 0, f"Concurrency test failed with {len(errors)} lock error(s)!"
    print("Part 2 Assertions Passed! Concurrent scans resolved cleanly under WAL mode.")
    
    # -------------------------------------------------------------
    # PART 3: Deep Tree Generator Output Assertion
    # -------------------------------------------------------------
    print("\n" + "="*60)
    print("TEST PART 3: DEEP SIDEBAR TREE STRUCTURE RESOLUTION")
    print("="*60)
    
    tree = generate_tree(repo_path)
    
    # Check that children are sorted (directories first, then files)
    # Let's find "packages" node
    packages_node = next((n for n in tree if n["name"] == "packages"), None)
    assert packages_node is not None, "Folder 'packages' not found in tree!"
    
    # In packages/a/b, verify directories ('c', 'sibling') come before files
    a_node = packages_node["children"][0]
    b_node = a_node["children"][0]
    
    child_types = [c["type"] for c in b_node["children"]]
    print(f"Child types under packages/a/b: {child_types}")
    print(f"Child names under packages/a/b: {[c['name'] for c in b_node['children']]}")
    
    # Directories ('c', 'sibling') must come before files
    # Here, we only have directories under 'b_node' (no files), but let's write a file to 'b_node' to assert
    with open(os.path.join(repo_path, "packages/a/b/file.py"), "w") as f:
        f.write("def f(): pass\n")
        
    tree_with_file = generate_tree(repo_path)
    packages_node_ref = next((n for n in tree_with_file if n["name"] == "packages"), None)
    a_node_ref = packages_node_ref["children"][0]
    b_node_ref = a_node_ref["children"][0]
    
    child_types_ref = [c["type"] for c in b_node_ref["children"]]
    child_names_ref = [c["name"] for c in b_node_ref["children"]]
    print(f"Refined Child types under packages/a/b: {child_types_ref}")
    print(f"Refined Child names under packages/a/b: {child_names_ref}")
    
    # Assert directories ('c', 'sibling') come before file ('file.py')
    assert child_types_ref[0] == "directory", "First child is not a directory!"
    assert child_types_ref[1] == "directory", "Second child is not a directory!"
    assert child_types_ref[2] == "file", "Third child is not a file!"
    
    print("Part 3 Assertions Passed! Hierarchical tree respects folder-first alphabetical ordering.")
    
    # Cleanup
    shutil.rmtree(repo_path)
    print("\nAll advanced test scenarios passed successfully!")

if __name__ == "__main__":
    run_advanced_tests()
