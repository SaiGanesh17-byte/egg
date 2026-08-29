import ast
import json
import sqlite3
import os
import re
import sys
sys.setrecursionlimit(50000)
from pathlib import Path
from typing import Dict, Any, List, Set
from .cpg_builder import GraphCollector
from .languages import get_parser_for_extension
from .parsers.python_parser import PythonParser
from .parsers.typescript_parser import TypeScriptParser
from .parsers.sql_parser import SQLParser
from .parsers.rust_parser import RustParser
from .parsers.go_parser import GoParser
from .parsers.java_parser import JavaParser

class EggEngine:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path).resolve().as_posix()
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self._init_db()

    def scan_directory(self, repo_path: str, progress_callback=None) -> Dict[str, int]:
        from .gitignore import GitIgnoreMatcher
        repo_path = Path(repo_path).resolve().as_posix()
        
        # Ensure database directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        
        matcher = GitIgnoreMatcher(repo_path)
        supported_exts = {".py", ".ts", ".tsx", ".js", ".jsx", ".sql", ".rs", ".go", ".java"}
        
        # Gather matching files
        files_to_index = []
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if not matcher.should_ignore(Path(root).joinpath(d).as_posix())]
            
            for file in files:
                file_path = Path(root).joinpath(file).as_posix()
                if matcher.should_ignore(file_path):
                    continue
                
                ext = Path(file).suffix.lower()
                if ext in supported_exts:
                    files_to_index.append(file_path)

        # -------------------------------------------------------------
        # PASS 1: Global Namespace Discovery
        # -------------------------------------------------------------
        total_files = len(files_to_index)
        print(f"[Egg Engine] Starting Pass 1 (Namespace Discovery) on {total_files} files...")
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for idx, file_path in enumerate(files_to_index, start=1):
                try:
                    rel_path = Path(file_path).relative_to(repo_path).as_posix()
                    # Clean previous definitions for this file
                    cur.execute("DELETE FROM discovered_declarations WHERE file_path = ?", (rel_path,))
                    
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        code = f.read()
                    
                    decls = self._discover_file_declarations(rel_path, code)
                    for qname, kind in decls:
                        cur.execute("""
                            INSERT OR REPLACE INTO discovered_declarations (qualified_name, decl_kind, file_path)
                            VALUES (?, ?, ?)
                        """, (qname, kind, rel_path))
                except Exception as e:
                    print(f"[Egg Engine] Pass 1 error on {file_path}: {e}")
                
                if progress_callback and (idx % 100 == 0 or idx == total_files):
                    progress_callback(idx, total_files, "pass1")
                    print(f"[Egg Engine] Pass 1: Discovered namespace symbols in {idx}/{total_files} files...")
            conn.commit()

        # -------------------------------------------------------------
        # PASS 2: Full CPG Indexing & Type Resolution
        # -------------------------------------------------------------
        print(f"[Egg Engine] Starting Pass 2 (CPG Indexing & Resolution)...")
        indexed_files = 0
        skipped_files = 0
        
        # Fetch defined classes and existing hashes once at start of Pass 2
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT qualified_name FROM discovered_declarations")
            defined_classes = {row[0] for row in cur.fetchall()}
            
            cur.execute("SELECT file_path, content_hash FROM file_hashes")
            existing_hashes = {row[0]: row[1] for row in cur.fetchall()}
        
        for idx, file_path in enumerate(files_to_index, start=1):
            try:
                rel_path = Path(file_path).relative_to(repo_path).as_posix()
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    code = f.read()
                
                # Check in-memory first to avoid database locking/query overhead for unchanged files
                collector = GraphCollector(rel_path, code)
                if existing_hashes.get(rel_path) == collector.file_hash:
                    skipped_files += 1
                    continue
                
                if self.process_file_with_data(rel_path, code, repo_path, defined_classes):
                    indexed_files += 1
                else:
                    skipped_files += 1
            except Exception as e:
                print(f"[Egg Engine] Pass 2 error on {file_path}: {e}")
                skipped_files += 1

            if progress_callback and (idx % 100 == 0 or idx == total_files):
                progress_callback(idx, total_files, "pass2")
                print(f"[Egg Engine] Pass 2: Indexed CPG nodes/edges in {idx}/{total_files} files...")
        
        # Clean up deleted files from the database (Garbage Collection)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT file_path FROM file_hashes")
            indexed_paths = [r[0] for r in cur.fetchall()]
            
            deleted_paths = []
            for rel_path in indexed_paths:
                abs_path = Path(repo_path).joinpath(rel_path).as_posix()
                if not os.path.exists(abs_path):
                    deleted_paths.append(rel_path)
            
            for rel_path in deleted_paths:
                cur.execute("DELETE FROM file_hashes WHERE file_path = ?", (rel_path,))
                cur.execute("DELETE FROM symbols WHERE file_path = ?", (rel_path,))
                cur.execute("DELETE FROM ai_contexts WHERE file_path = ?", (rel_path,))
                cur.execute("DELETE FROM discovered_declarations WHERE file_path = ?", (rel_path,))
                cur.execute("DELETE FROM class_hierarchy WHERE child_id LIKE ?", (f"{rel_path}%",))
                cur.execute("DELETE FROM instantiations WHERE file_path = ?", (rel_path,))
                
                escaped_path = rel_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                cur.execute("DELETE FROM graph_edges WHERE source_id LIKE ? ESCAPE '\\' OR target_id LIKE ? ESCAPE '\\'", 
                            (f"{escaped_path}%", f"{escaped_path}%"))
                
            conn.commit()
            if deleted_paths:
                print(f"[Egg Engine] Purged {len(deleted_paths)} deleted files from database.")

        self.resolve_cross_language_dependencies(repo_path)
        self.resolve_structural_go_interfaces()
                        
        return {
            "total_files": total_files,
            "indexed_files": indexed_files,
            "skipped_files": skipped_files
        }

    def _discover_file_declarations(self, file_path: str, source_code: str) -> List[tuple[str, str]]:
        ext = Path(file_path).suffix.lower()
        parser = get_parser_for_extension(ext)
        if not parser:
            return []
        try:
            tree = parser.parse(bytes(source_code, "utf-8"))
        except Exception:
            return []

        if ext == ".java":
            return JavaParser.discover_namespace(file_path, source_code, tree)
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            return TypeScriptParser.discover_namespace(file_path, source_code, tree)
        elif ext == ".go":
            return GoParser.discover_namespace(file_path, source_code, tree)
        elif ext == ".rs":
            return RustParser.discover_namespace(file_path, source_code, tree)
        return []

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            schema_sql = """
            CREATE TABLE IF NOT EXISTS symbols (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                file_path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                signature TEXT,
                content_hash TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_name_kind ON symbols (name, kind);
            CREATE TABLE IF NOT EXISTS graph_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                label TEXT,
                PRIMARY KEY (source_id, target_id, edge_type, label)
            );
            CREATE TABLE IF NOT EXISTS file_hashes (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ai_contexts (
                symbol_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                context_payload JSON NOT NULL,
                status TEXT DEFAULT 'PENDING',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(symbol_id) REFERENCES symbols(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS discovered_declarations (
                qualified_name TEXT PRIMARY KEY,
                decl_kind TEXT NOT NULL,
                file_path TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS class_hierarchy (
                child_id TEXT NOT NULL,
                parent_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                unqualified INTEGER DEFAULT 0,
                PRIMARY KEY (child_id, parent_id)
            );
            CREATE TABLE IF NOT EXISTS instantiations (
                class_id TEXT NOT NULL,
                instantiation_type TEXT NOT NULL,
                file_path TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                PRIMARY KEY (class_id, file_path, line_number)
            );
            """
            conn.executescript(schema_sql)

    def should_reindex(self, file_path: str, content_hash: str) -> bool:
        file_path = Path(file_path).as_posix()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT content_hash FROM file_hashes WHERE file_path = ?", (file_path,))
            row = cur.fetchone()
            return row is None or row[0] != content_hash

    def process_file(self, file_path: str, source_code: str, repo_path: str) -> bool:
        file_path = Path(file_path).as_posix()
        collector = GraphCollector(file_path, source_code)
        if not self.should_reindex(file_path, collector.file_hash):
            return False
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT qualified_name FROM discovered_declarations")
            defined_classes = {row[0] for row in cur.fetchall()}
        return self.process_file_with_data(file_path, source_code, repo_path, defined_classes)

    def process_file_with_data(self, file_path: str, source_code: str, repo_path: str, defined_classes: set) -> bool:
        file_path = Path(file_path).as_posix()
        collector = GraphCollector(file_path, source_code)

        ext = Path(file_path).suffix.lower()
        parser = get_parser_for_extension(ext)
        if not parser:
            return False

        try:
            tree = parser.parse(bytes(source_code, "utf-8"))
        except Exception as e:
            return False

        if ext == ".py":
            visitor = PythonParser(file_path, source_code, collector)
        elif ext in (".ts", ".tsx", ".js", ".jsx"):
            visitor = TypeScriptParser(file_path, source_code, collector, self.db_path, defined_classes)
        elif ext == ".sql":
            visitor = SQLParser(file_path, source_code, collector)
        elif ext == ".rs":
            visitor = RustParser(file_path, source_code, collector, self.db_path, defined_classes)
        elif ext == ".go":
            visitor = GoParser(file_path, source_code, collector, self.db_path, defined_classes)
        elif ext == ".java":
            visitor = JavaParser(file_path, source_code, collector, self.db_path, defined_classes)
        else:
            return False

        try:
            visitor.parse(tree.root_node)
        except Exception as e:
            return False

        self._save_to_db(collector)
        return True

    def _save_to_db(self, collector: GraphCollector):
        with sqlite3.connect(self.db_path) as conn:
            self._save_to_db_with_conn(collector, conn)
            conn.commit()

    def _save_to_db_with_conn(self, collector: GraphCollector, conn):
        norm_path = Path(collector.file_path).as_posix()
        cur = conn.cursor()

        # Clean previous graph slice for this file
        cur.execute("DELETE FROM symbols WHERE file_path = ?", (norm_path,))
        
        # Safe cross-platform wildcard cleaning using explicit ESCAPE keyword
        escaped_path = norm_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cur.execute("DELETE FROM graph_edges WHERE source_id LIKE ? ESCAPE '\\' OR target_id LIKE ? ESCAPE '\\'", 
                    (f"{escaped_path}%", f"{escaped_path}%"))
        
        cur.execute("DELETE FROM ai_contexts WHERE file_path = ?", (norm_path,))

        for node in collector.nodes.values():
            node_id = Path(node.id).as_posix() if "::" not in node.id else node.id
            cur.execute("""
                INSERT OR REPLACE INTO symbols (id, name, kind, file_path, start_line, end_line, signature, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (node_id, node.name, node.kind, norm_path, node.start_line, node.end_line, node.signature, collector.file_hash))

        for edge in collector.edges:
            cur.execute("""
                INSERT OR IGNORE INTO graph_edges (source_id, target_id, edge_type, label)
                VALUES (?, ?, ?, ?)
            """, (edge.source, edge.target, edge.edge_type, edge.label))

        for node_id, node in collector.nodes.items():
            if node.kind == "FUNCTION":
                payload = self._generate_ai_payload(collector, node_id)
                cur.execute("""
                    INSERT OR REPLACE INTO ai_contexts (symbol_id, file_path, context_payload, status)
                    VALUES (?, ?, ?, 'PENDING')
                """, (node_id, norm_path, json.dumps(payload)))

        cur.execute("""
            INSERT OR REPLACE INTO file_hashes (file_path, content_hash, last_indexed)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (norm_path, collector.file_hash))

    def _generate_ai_payload(self, collector: GraphCollector, symbol_id: str) -> Dict[str, Any]:
        target_node = collector.nodes[symbol_id]
        
        callers = [e.source for e in collector.edges if e.target == symbol_id and e.edge_type == "CALLS"]
        callees = [e.target for e in collector.edges if e.source == symbol_id and e.edge_type == "CALLS"]
        
        owned_stmts = {e.target for e in collector.edges if e.source == symbol_id and e.edge_type == "AST"}
        mutated_vars = [e.label for e in collector.edges if e.source in owned_stmts and e.edge_type == "DFG" and e.label]

        return {
            "symbol_id": symbol_id,
            "name": target_node.name,
            "kind": target_node.kind,
            "file_path": Path(target_node.file_path).as_posix(),
            "lines": f"{target_node.start_line}-{target_node.end_line}",
            "signature": target_node.signature,
            "call_graph": {
                "invoked_by": list(set(callers)),
                "calls_to": list(set(callees))
            },
            "data_flow": {
                "mutated_state": list(set(mutated_vars))
            }
        }

    def resolve_call_site(self, declared_type: str, method_name: str, cursor) -> Dict[str, Any]:
        """
        Resolves the candidates for a method invocation on a declared type using RTA/CHA.
        """
        # 1. Fetch subclasses recursively using cycle-guarded Recursive CTE
        cursor.execute("""
            WITH RECURSIVE inheritance_tree(child_id, parent_id, path_unqualified, depth) AS (
                SELECT child_id, parent_id, unqualified, 1
                FROM class_hierarchy
                WHERE parent_id = ?
                
                UNION ALL
                
                SELECT ch.child_id, ch.parent_id, (it.path_unqualified | ch.unqualified), it.depth + 1
                FROM class_hierarchy ch
                JOIN inheritance_tree it ON ch.parent_id = it.child_id
                WHERE it.depth < 20
            )
            SELECT child_id, MAX(path_unqualified) AS path_unqualified
            FROM inheritance_tree
            GROUP BY child_id;
        """, (declared_type,))
        
        raw_candidates = cursor.fetchall()
        
        # If no subclass implementations are found, assume static dispatch
        if not raw_candidates:
            return {
                "resolution": "static-assumed",
                "classes": [declared_type]
            }

        # Filter subclasses to only those that actually define or inherit the method.
        # We query the `symbols` table to verify the method exists for that class.
        # In our schema, a method ID has the form 'file.java::ClassName.methodName(ParamTypes)'
        # or 'file.java::ClassName.methodName'. We match prefix 'candidate_id.method_name'.
        cursor.execute("""
            SELECT id FROM symbols 
            WHERE name = ? AND kind = 'FUNCTION'
        """, (method_name,))
        matching_ids = [r[0] for r in cursor.fetchall()]

        filtered_candidates = []
        for qid, unqualified in raw_candidates:
            # Check if this class defines the method
            simple_class = qid.split('.')[-1]
            has_method = any(
                f"::{simple_class}.{method_name}(" in mid or mid.endswith(f"::{simple_class}.{method_name}")
                for mid in matching_ids
            )
            if has_method:
                filtered_candidates.append((qid, unqualified))

        # If no candidate subclasses override the method, default back to declared type
        if not filtered_candidates:
            return {
                "resolution": "static-assumed",
                "classes": [declared_type]
            }

        candidate_map = {qid: bool(unq) for qid, unq in filtered_candidates}

        # 2. Query instantiations using qualified class IDs
        placeholders = ",".join("?" for _ in candidate_map.keys())
        cursor.execute(
            f"SELECT DISTINCT class_id FROM instantiations WHERE class_id IN ({placeholders})",
            list(candidate_map.keys())
        )
        instantiated_qids = {r[0] for r in cursor.fetchall()}

        # 3. Categorize tags based on instantiation evidence
        cursor.execute("SELECT COUNT(*) FROM instantiations")
        rta_data_missing = cursor.fetchone()[0] == 0

        # CASE A: No RTA instantiation data globally indexed
        if rta_data_missing:
            return {
                "resolution": "cha-unfiltered",
                "classes": list(candidate_map.keys())
            }

        # Filter to active instantiations
        rta_classes = [
            (qid, is_unq)
            for qid, is_unq in candidate_map.items()
            if qid in instantiated_qids
        ]

        # CASE B: RTA ran, but none of these candidates are instantiated (dead / external code)
        if not rta_classes:
            return {
                "resolution": "cha-dead-or-external",
                "classes": list(candidate_map.keys())
            }

        # CASE C: Multiple candidates instantiated
        if len(rta_classes) > 1:
            return {
                "resolution": "rta-narrowed",
                "classes": [qid for qid, _ in rta_classes]
            }

        # CASE D: Exactly one instantiated subclass remains
        surviving_qid, is_unqualified = rta_classes[0]
        if is_unqualified:
            return {
                "resolution": "rta-resolved-tentative",
                "classes": [surviving_qid]
            }
        else:
            return {
                "resolution": "rta-resolved",
                "classes": [surviving_qid]
            }

    def resolve_structural_go_interfaces(self):
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            
            # Get all Go interfaces
            cur.execute("""
                SELECT s.id, s.name, s.file_path, d.qualified_name 
                FROM symbols s
                JOIN discovered_declarations d ON s.file_path = d.file_path 
                    AND (d.qualified_name = s.name OR d.qualified_name LIKE ('%.' || s.name))
                WHERE s.kind = 'CLASS' AND s.signature LIKE '%interface%' AND s.file_path LIKE '%.go'
            """)
            interfaces = cur.fetchall()
            
            # Get all Go structs
            cur.execute("""
                SELECT s.id, s.name, s.file_path, d.qualified_name 
                FROM symbols s
                JOIN discovered_declarations d ON s.file_path = d.file_path 
                    AND (d.qualified_name = s.name OR d.qualified_name LIKE ('%.' || s.name))
                WHERE s.kind = 'CLASS' AND s.signature LIKE '%struct%' AND s.file_path LIKE '%.go'
            """)
            structs = cur.fetchall()
            
            if not interfaces or not structs:
                return

            # Map of interface_id -> list of method specs: (name, clean_signature)
            iface_methods = {}
            for iface_id, iface_name, iface_fp, iface_qname in interfaces:
                cur.execute("SELECT name, signature FROM symbols WHERE kind = 'FUNCTION' AND id LIKE ?", (f"{iface_id}.%",))
                specs = []
                for m_name, m_sig in cur.fetchall():
                    # clean signature (strip method name and spaces)
                    clean_sig = m_sig.replace(m_name, "", 1).replace(" ", "").strip()
                    specs.append((m_name, clean_sig))
                if specs: # Skip empty interface{} matching
                    iface_methods[iface_id] = (iface_qname, specs)

            # Map of struct_id -> list of implemented method specs: (name, clean_signature)
            struct_methods = {}
            for struct_id, struct_name, struct_fp, struct_qname in structs:
                cur.execute("SELECT name, signature FROM symbols WHERE kind = 'FUNCTION' AND id LIKE ?", (f"{struct_id}.%",))
                specs = []
                for m_name, m_sig in cur.fetchall():
                    # struct method sig: func (s *Struct) Read(p []byte) (n int, err error)
                    clean_sig = m_sig
                    if "func (" in clean_sig:
                        parts = clean_sig.split(")", 1)
                        if len(parts) > 1:
                            clean_sig = parts[1].strip()
                    clean_sig = clean_sig.replace(m_name, "", 1).replace(" ", "").strip()
                    specs.append((m_name, clean_sig))
                struct_methods[struct_id] = (struct_qname, specs)

            # Match
            new_implements = []
            for struct_id, (struct_qname, s_specs) in struct_methods.items():
                s_map = {name: sig for name, sig in s_specs}
                for iface_id, (iface_qname, i_specs) in iface_methods.items():
                    satisfies = True
                    for i_name, i_sig in i_specs:
                        if i_name not in s_map or s_map[i_name] != i_sig:
                            satisfies = False
                            break
                    if satisfies:
                        new_implements.append((struct_qname, iface_qname, 'IMPLEMENTS', 0))

            if new_implements:
                cur.executemany("""
                    INSERT OR IGNORE INTO class_hierarchy (child_id, parent_id, relation_type, unqualified)
                    VALUES (?, ?, ?, ?)
                """, new_implements)
                conn.commit()
                print(f"[Go Resolver] Implemented structural matching: resolved {len(new_implements)} interface satisfaction links.")

    def resolve_cross_language_dependencies(self, repo_path: str):
        repo_path = Path(repo_path).resolve().as_posix()
        table_symbols = []
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name FROM symbols WHERE kind = 'TABLE'")
            table_symbols = cur.fetchall()

        if not table_symbols:
            return

        patterns = [
            re.compile(r"\bfrom\s+([a-zA-Z_]\w*)", re.IGNORECASE),
            re.compile(r"\binto\s+([a-zA-Z_]\w*)", re.IGNORECASE),
            re.compile(r"\bupdate\s+([a-zA-Z_]\w*)", re.IGNORECASE),
            re.compile(r"\bjoin\s+([a-zA-Z_]\w*)", re.IGNORECASE),
            re.compile(r"\bdb\.([a-zA-Z_]\w*)", re.IGNORECASE)
        ]

        table_map = {name.lower(): symbol_id for symbol_id, name in table_symbols}

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, file_path, start_line, end_line FROM symbols WHERE kind IN ('FUNCTION', 'ASSIGN')")
            symbols_to_check = cur.fetchall()

        file_cache = {}
        new_edges = []
        
        for symbol_id, rel_file_path, start_line, end_line in symbols_to_check:
            abs_file_path = Path(repo_path).joinpath(rel_file_path).as_posix()
            if not os.path.exists(abs_file_path):
                continue

            if abs_file_path not in file_cache:
                try:
                    with open(abs_file_path, "r", encoding="utf-8", errors="ignore") as f:
                        file_cache[abs_file_path] = f.readlines()
                except Exception as e:
                    print(f"[Egg Engine] Error reading {abs_file_path} for dependency resolution: {e}")
                    continue

            lines = file_cache[abs_file_path]
            start_idx = max(0, start_line - 1)
            end_idx = min(len(lines), end_line)
            symbol_code = "".join(lines[start_idx:end_idx])

            referenced_tables = set()
            for pat in patterns:
                for match in pat.finditer(symbol_code):
                    tbl = match.group(1).lower()
                    if tbl in table_map:
                        referenced_tables.add(table_map[tbl])

            for target_table_id in referenced_tables:
                new_edges.append((symbol_id, target_table_id, "DATA_ACCESS", f"references table"))

        if new_edges:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.executemany("""
                    INSERT OR IGNORE INTO graph_edges (source_id, target_id, edge_type, label)
                    VALUES (?, ?, ?, ?)
                """, new_edges)
                conn.commit()
            print(f"[Egg Engine] Resolved {len(new_edges)} cross-language SQL dependencies.")
