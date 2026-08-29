from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import re
import sqlite3
from typing import Dict, Any, List, Set
from egg.core.engine import EggEngine
from egg.core.tree_builder import generate_tree

import threading
scan_lock = threading.Lock()

scan_progress = {
    "total": 0,
    "current": 0,
    "phase": "idle"  # "idle", "pass1", "pass2", "complete"
}

def update_progress(current: int, total: int, phase: str):
    global scan_progress
    scan_progress["current"] = current
    scan_progress["total"] = total
    scan_progress["phase"] = phase

app = FastAPI(title="Egg - Documentation Engine API")

# Allow CORS for development simplicity
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    repo_path: str
    db_storage_path: str


def get_db_path_for_repo(repo_path: str, db_storage_path: str) -> str:
    clean_repo = os.path.abspath(repo_path)
    safe_name = clean_repo.strip("/\\").replace("/", "_").replace("\\", "_").replace(":", "")
    return os.path.join(db_storage_path, safe_name, "graph.db")


@app.post("/api/scan")
def scan_repository(request: ScanRequest):
    repo_path = os.path.abspath(request.repo_path)
    db_storage_path = os.path.abspath(request.db_storage_path)
    
    if not os.path.isdir(repo_path):
        raise HTTPException(
            status_code=400, detail=f"Provided path '{repo_path}' is not a directory.")
    if not os.path.isdir(db_storage_path):
        raise HTTPException(
            status_code=400, detail=f"Database storage path '{db_storage_path}' is not a directory. Please create it or configure it in Settings.")

    with scan_lock:
        try:
            import time
            start_time = time.time()
            update_progress(0, 0, "pass1")
            
            db_path = get_db_path_for_repo(repo_path, db_storage_path)
            engine = EggEngine(db_path)
            stats = engine.scan_directory(repo_path, progress_callback=update_progress)
            update_progress(100, 100, "complete")
    
            # Query total indexed nodes (symbols) in SQLite DB
            node_count = 0
            if os.path.exists(db_path):
                try:
                    with sqlite3.connect(db_path) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT COUNT(*) FROM symbols")
                        node_count = cur.fetchone()[0]
                except Exception as db_err:
                    print(f"[Egg Server] Error reading SQLite count: {db_err}")
    
            return {
                "status": "success",
                "repo_path": repo_path,
                "db_path": db_path,
                "total_files": stats["total_files"],
                "indexed_files": stats["indexed_files"],
                "skipped_files": stats["skipped_files"],
                "node_count": node_count,
                "scan_time_seconds": round(time.time() - start_time, 2)
            }
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to scan repository: {str(e)}")


@app.get("/api/scan_progress")
def get_scan_progress():
    return scan_progress


@app.get("/api/tree")
def get_file_tree(repo_path: str = Query(..., description="Path to the repository")):
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        raise HTTPException(
            status_code=400, detail=f"Provided path '{repo_path}' is not a directory.")

    try:
        tree = generate_tree(repo_path)
        return {
            "status": "success",
            "repo_path": repo_path,
            "tree": tree
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate file tree: {str(e)}")


@app.get("/api/file_details")
def get_file_details(
    repo_path: str = Query(...), 
    db_storage_path: str = Query(...), 
    file_path: str = Query(...)
):
    repo_path = os.path.abspath(repo_path)
    db_storage_path = os.path.abspath(db_storage_path)
    abs_file_path = os.path.join(repo_path, file_path)
    
    if not os.path.isfile(abs_file_path):
        raise HTTPException(status_code=400, detail=f"File not found: {file_path}")
        
    try:
        with open(abs_file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        db_path = get_db_path_for_repo(repo_path, db_storage_path)
        symbols = []
        edges = []
        if os.path.exists(db_path):
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id, name, kind, start_line, end_line, signature 
                    FROM symbols 
                    WHERE file_path = ?
                """, (file_path,))
                symbols = [
                    {
                        "id": r[0],
                        "name": r[1],
                        "kind": r[2],
                        "start_line": r[3],
                        "end_line": r[4],
                        "signature": r[5]
                    }
                    for r in cur.fetchall()
                ]
                
                # Fetch related edges
                symbol_ids = [s["id"] for s in symbols]
                if symbol_ids:
                    placeholders = ",".join("?" for _ in symbol_ids)
                    cur.execute(f"""
                        SELECT source_id, target_id, edge_type, label 
                        FROM graph_edges 
                        WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})
                    """, symbol_ids + symbol_ids)
                    edges = [
                        {
                            "source": r[0],
                            "target": r[1],
                            "type": r[2],
                            "label": r[3]
                        }
                        for r in cur.fetchall()
                    ]
        
        return {
            "status": "success",
            "content": content,
            "symbols": symbols,
            "edges": edges
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/db_stats")
def get_db_stats(repo_path: str = Query(...), db_storage_path: str = Query(...)):
    repo_path = os.path.abspath(repo_path)
    db_storage_path = os.path.abspath(db_storage_path)
    
    db_path = get_db_path_for_repo(repo_path, db_storage_path)
    if not os.path.exists(db_path):
        raise HTTPException(status_code=400, detail="CPG database not found for this repository.")
        
    try:
        symbols_summary = {}
        edges_summary = {}
        sql_tables = []
        total_symbols = 0
        total_edges = 0
        
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            
            cur.execute("SELECT kind, COUNT(*) FROM symbols GROUP BY kind")
            for kind, cnt in cur.fetchall():
                symbols_summary[kind] = cnt
                total_symbols += cnt
                
            cur.execute("SELECT edge_type, COUNT(*) FROM graph_edges GROUP BY edge_type")
            for etype, cnt in cur.fetchall():
                edges_summary[etype] = cnt
                total_edges += cnt
                
            cur.execute("SELECT id, name FROM symbols WHERE kind = 'TABLE' ORDER BY name")
            sql_tables = [{"id": r[0], "name": r[1]} for r in cur.fetchall()]
            
            # Query type-resolution confidence summary
            cur.execute("""
                SELECT DISTINCT target_id FROM graph_edges 
                WHERE edge_type = 'CALLS' AND target_id IS NOT NULL
            """)
            targets = [r[0] for r in cur.fetchall()]
            
            confidence_summary = {
                "high": 0,
                "medium": 0,
                "low": 0
            }
            
            from egg.core.engine import EggEngine
            engine = EggEngine(db_path)
            
            for target in targets:
                if "." in target:
                    parts = target.split(".")
                    method_name = parts[-1]
                    declared_type = ".".join(parts[:-1])
                    
                    res = engine.resolve_call_site(declared_type, method_name, cur)
                    resolution = res["resolution"]
                    
                    if resolution == "rta-resolved":
                        confidence_summary["high"] += 1
                    elif resolution in ("rta-narrowed", "rta-resolved-tentative", "static-assumed"):
                        confidence_summary["medium"] += 1
                    else:
                        confidence_summary["low"] += 1
                else:
                    confidence_summary["low"] += 1
            
        return {
            "status": "success",
            "total_symbols": total_symbols,
            "total_edges": total_edges,
            "symbols_summary": symbols_summary,
            "edges_summary": edges_summary,
            "sql_tables": sql_tables,
            "confidence_summary": confidence_summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query database statistics: {str(e)}")


def _infer_receiver_type(code: str, receiver_name: str, enclosing_class: str) -> str:
    if receiver_name == "this" or receiver_name == "self":
        return enclosing_class
    # Java/Go/TS variable declaration matching
    pat_java = re.compile(r"\b([A-Z]\w+)\s+" + re.escape(receiver_name) + r"\b")
    m = pat_java.search(code)
    if m:
        return m.group(1)
    pat_ts = re.compile(re.escape(receiver_name) + r"\s*:\s*([A-Z]\w+)\b")
    m = pat_ts.search(code)
    if m:
        return m.group(1)
    # Default fallback
    return receiver_name[0].upper() + receiver_name[1:] if receiver_name else enclosing_class


def _get_contained_assign_nodes(parent_id: str, cur) -> List[tuple]:
    cur.execute("""
        SELECT s.id, s.name, s.kind, s.start_line, s.end_line 
        FROM graph_edges e
        JOIN symbols s ON e.target_id = s.id
        WHERE e.source_id = ? AND e.edge_type = 'AST'
    """, (parent_id,))
    children = cur.fetchall()
    
    assign_nodes = []
    for c_id, c_name, c_kind, c_start, c_end in children:
        if c_kind == "FUNCTION":
            continue
        if c_kind == "ASSIGN":
            assign_nodes.append((c_id, c_name, c_kind, c_start, c_end))
        assign_nodes.extend(_get_contained_assign_nodes(c_id, cur))
        
    return assign_nodes

def _get_ancestry_path(node_id: str, cur) -> List[str]:
    path = [node_id]
    curr = node_id
    while curr:
        cur.execute("SELECT source_id FROM graph_edges WHERE target_id = ? AND edge_type = 'AST'", (curr,))
        row = cur.fetchone()
        if row:
            path.append(row[0])
            curr = row[0]
        else:
            break
    path.reverse()
    return path

def _check_exclusivity(t_i: str, t_j: str, cur) -> bool:
    path_i = _get_ancestry_path(t_i, cur)
    path_j = _get_ancestry_path(t_j, cur)
    
    lca = None
    lca_idx = -1
    min_len = min(len(path_i), len(path_j))
    for k in range(min_len):
        if path_i[k] == path_j[k]:
            lca = path_i[k]
            lca_idx = k
        else:
            break
            
    if not lca:
        return False
        
    # Check if LCA is of kind BRANCH
    cur.execute("SELECT kind FROM symbols WHERE id = ?", (lca,))
    row = cur.fetchone()
    if row and row[0] == "BRANCH":
        # Get the immediate child of the LCA in both paths
        if lca_idx + 1 < len(path_i) and lca_idx + 1 < len(path_j):
            child_i = path_i[lca_idx + 1]
            child_j = path_j[lca_idx + 1]
            # Check if they are different BRANCH_ARM nodes
            cur.execute("SELECT kind FROM symbols WHERE id = ?", (child_i,))
            row_i = cur.fetchone()
            cur.execute("SELECT kind FROM symbols WHERE id = ?", (child_j,))
            row_j = cur.fetchone()
            if row_i and row_i[0] == "BRANCH_ARM" and row_j and row_j[0] == "BRANCH_ARM":
                if child_i != child_j:
                    return True
    return False

def _partition_targets(targets: List[str], cur) -> List[dict]:
    if not targets:
        return []
        
    n = len(targets)
    adj = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _check_exclusivity(targets[i], targets[j], cur):
                adj[i].add(j)
                adj[j].add(i)
                
    visited = set()
    components = []
    for i in range(n):
        if i not in visited:
            comp = []
            queue = [i]
            visited.add(i)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            components.append(comp)
            
    groups = []
    unconditional_targets = []
    
    # Invariant comment: connected components are expected to always form cliques 
    # given well-formed BRANCH/BRANCH_ARM structure.
    for comp in components:
        comp_targets = [targets[idx] for idx in comp]
        if len(comp_targets) >= 2:
            names = []
            for t_id in comp_targets:
                cur.execute("SELECT name FROM symbols WHERE id = ?", (t_id,))
                row = cur.fetchone()
                names.append(row[0] if row else t_id.split("::")[-1])
            groups.append({
                "targets": sorted(list(set(names))),
                "flow_type": "conditional_branch"
            })
        else:
            unconditional_targets.append(comp_targets[0])
            
    if unconditional_targets:
        names = []
        for t_id in unconditional_targets:
            cur.execute("SELECT name FROM symbols WHERE id = ?", (t_id,))
            row = cur.fetchone()
            names.append(row[0] if row else t_id.split("::")[-1])
            
        names = sorted(list(set(names)))
        if len(names) == 1:
            groups.append({
                "targets": names,
                "flow_type": "sequential"
            })
        else:
            groups.append({
                "targets": names,
                "flow_type": "fan_out"
            })
            
    return groups


@app.get("/api/cpg_slice")
def get_cpg_slice(
    repo_path: str = Query(...),
    db_storage_path: str = Query(...),
    symbol_id: str = Query(...)
):
    repo_path = os.path.abspath(repo_path)
    db_storage_path = os.path.abspath(db_storage_path)
    db_path = get_db_path_for_repo(repo_path, db_storage_path)

    if not os.path.exists(db_path):
        raise HTTPException(status_code=400, detail="Repository not indexed yet. Run scan first.")

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            
            # 1. Fetch Symbol Node
            cur.execute("""
                SELECT id, name, kind, file_path, start_line, end_line, signature 
                FROM symbols WHERE id = ?
            """, (symbol_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Symbol '{symbol_id}' not found.")

            s_id, name, kind, file_path, start_line, end_line, signature = row
            
            # Read code snippet
            abs_file = os.path.join(repo_path, file_path)
            code_snippet = ""
            if os.path.exists(abs_file):
                with open(abs_file, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    code_snippet = "".join(lines[start_line - 1:end_line])

            # Get enclosing class from symbol_id context
            # e.g., 'path/file.java::RealVideoObject.accept(Visitor)' -> 'RealVideoObject'
            enclosing_class = "unknown"
            if "::" in s_id:
                parts = s_id.split("::", 1)[1].split(".")
                if len(parts) > 1:
                    enclosing_class = parts[0]

            # 2. Query calls_out_to (Outgoing Calls)
            # Find AST invocation nodes belonging to this function
            cur.execute("SELECT target_id, label FROM graph_edges WHERE source_id = ? AND edge_type = 'CALLS'", (s_id,))
            raw_calls = cur.fetchall()

            engine = EggEngine(db_path)
            calls_out_to = []
            boundary_warnings = []

            # Truncation limit for warnings check
            CALLS_LIMIT = 10
            if len(raw_calls) > CALLS_LIMIT:
                boundary_warnings.append({
                    "symbol": s_id,
                    "omitted_count": len(raw_calls) - CALLS_LIMIT,
                    "reason": "Exceeded slice outgoing call representation limit",
                    "follow_up_tool": f"get_calls_from({s_id})"
                })
                raw_calls = raw_calls[:CALLS_LIMIT]

            for target_id, label in raw_calls:
                # Resolve declared receiver type
                # e.g., label='video.accept', target_id='accept'
                receiver_name = "this"
                method_name = target_id
                if label and "." in label:
                    receiver_name, method_name = label.split(".", 1)

                declared_type = _infer_receiver_type(code_snippet, receiver_name, enclosing_class)
                
                # Fetch fully qualified receiver ID if declared_type is simple name
                # (Look it up in discovered declarations matching defined type suffix)
                cur.execute("""
                    SELECT qualified_name FROM discovered_declarations 
                    WHERE qualified_name = ? OR qualified_name LIKE ?
                """, (declared_type, f"%.{declared_type}"))
                res_qname = cur.fetchone()
                if res_qname:
                    declared_type = res_qname[0]

                # Run resolution
                res = engine.resolve_call_site(declared_type, method_name, cur)
                
                # Confidence mapping
                confidence_map = {
                    "static-assumed": "medium",
                    "cha-unfiltered": "low",
                    "cha-dead-or-external": "low",
                    "rta-narrowed": "medium",
                    "rta-resolved-tentative": "medium",
                    "rta-resolved": "high"
                }
                confidence = confidence_map.get(res["resolution"], "low")

                # Get code preview snippet from one of the candidates
                code_preview = None
                if res["classes"]:
                    candidate_class = res["classes"][0]
                    # Find constructor/method body in symbols matching candidate path
                    cur.execute("""
                        SELECT start_line, end_line, file_path FROM symbols 
                        WHERE (id LIKE ? OR id LIKE ?) AND kind = 'FUNCTION'
                    """, (f"%::{candidate_class.split('.')[-1]}.{method_name}%", f"%::{method_name}"))
                    meth_row = cur.fetchone()
                    if meth_row:
                        m_start, m_end, m_fp = meth_row
                        abs_m_file = os.path.join(repo_path, m_fp)
                        if os.path.exists(abs_m_file):
                            with open(abs_m_file, "r", encoding="utf-8", errors="ignore") as f:
                                m_lines = f.readlines()
                                code_preview = "".join(m_lines[m_start - 1:m_end])

                calls_out_to.append({
                    "call_site_line": start_line,  # Approximated to method body header or relative line
                    "target_name": method_name,
                    "resolution": res["resolution"],
                    "confidence": confidence,
                    "candidates": res["classes"],
                    "code_preview": code_preview
                })

            # 3. Query DFG data_flow DAG
            # Gather variables declared or mutated inside function scope using AST-containment
            assign_nodes = _get_contained_assign_nodes(s_id, cur)
            
            data_flow = []
            
            # A. Process Parameters (outgoing DFG edges from the function node s_id)
            cur.execute("""
                SELECT DISTINCT label FROM graph_edges 
                WHERE source_id = ? AND edge_type = 'DFG' AND label IS NOT NULL
            """, (s_id,))
            param_names = [r[0] for r in cur.fetchall()]
            
            for p_name in param_names:
                cur.execute("""
                    SELECT target_id FROM graph_edges 
                    WHERE source_id = ? AND edge_type = 'DFG' AND label = ?
                """, (s_id, p_name))
                targets = [r[0] for r in cur.fetchall()]
                
                flows_to_groups = _partition_targets(targets, cur)
                data_flow.append({
                    "symbol": p_name,
                    "operation": "parameter",
                    "flows_to": flows_to_groups,
                    "line": start_line
                })

            # B. Process Assignments
            for a_id, a_name, a_kind, a_start, a_end in assign_nodes:
                cur.execute("SELECT target_id FROM graph_edges WHERE source_id = ? AND edge_type = 'DFG'", (a_id,))
                targets = [r[0] for r in cur.fetchall()]
                
                flows_to_groups = _partition_targets(targets, cur)
                data_flow.append({
                    "symbol": a_name,
                    "operation": "assign",
                    "flows_to": flows_to_groups,
                    "line": a_start
                })

            # Sort topologically by line number
            data_flow.sort(key=lambda x: x.get("line", 0))
            
            # Clean up line key from output response
            for df in data_flow:
                if "line" in df:
                    del df["line"]

            return {
                "symbol_id": symbol_id,
                "code_snippet": code_snippet,
                "kind": kind,
                "calls_out_to": calls_out_to,
                "data_flow": data_flow,
                "boundary_warnings": boundary_warnings
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate context slice: {str(e)}")
