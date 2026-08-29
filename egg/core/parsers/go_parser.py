import sqlite3
from tree_sitter import Node
from typing import List, Dict, Set, Optional
from .base_parser import BaseParser

class GoParser(BaseParser):
    def __init__(self, file_path: str, source_code: str, collector, db_path: str = None, defined_classes: Set[str] = None):
        super().__init__(file_path, source_code, collector)
        self.db_path = db_path
        self.defined_classes = defined_classes or set()
        self.current_scope: List[str] = []
        self.scope_defs: List[Dict[str, Set[str]]] = [{}]
        self.last_cfg_nodes: List[str] = []
        self.package_name = ""

    @staticmethod
    def discover_namespace(file_path: str, source_code: str, tree) -> List[tuple]:
        package_name = ""
        results = []
        source_bytes = source_code.encode("utf-8")
        
        # Extract package name
        for child in tree.root_node.children:
            if child.type == "package_clause":
                for sub in child.children:
                    if sub.type in ("package_identifier", "identifier"):
                        package_name = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
                        break
                break

        # Walk nodes to find struct/interface specs
        def walk(n):
            if n.type == "type_spec":
                name_node = n.child_by_field_name("name")
                type_node = n.child_by_field_name("type")
                if name_node and type_node and type_node.type in ("struct_type", "interface_type"):
                    simple_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                    qualified_name = f"{package_name}.{simple_name}" if package_name else simple_name
                    results.append((qualified_name, "CLASS"))
            # Skip block statement/function bodies during discovery
            if n.type == "block":
                return
            for c in n.children:
                walk(c)
        walk(tree.root_node)
        return results

    def parse(self, root_node: Node):
        # Extract package name
        for child in root_node.children:
            if child.type == "package_clause":
                for sub in child.children:
                    if sub.type in ("package_identifier", "identifier"):
                        self.package_name = self._get_text(sub).strip()
                        break
                break
        self.visit(root_node)

    def _extract_identifiers(self, node: Node) -> List[str]:
        if node is None:
            return []
        ids = []
        if node.type == "identifier":
            ids.append(self._get_text(node))
        elif node.type == "field_identifier":
            ids.append(self._get_text(node))
        elif node.type == "selector_expression":
            ids.append(self._get_text(node))
        else:
            for child in node.children:
                ids.extend(self._extract_identifiers(child))
        return ids

    def _extract_receiver_type(self, node: Node) -> str:
        if node.type == "type_identifier":
            return self._get_text(node)
        for child in node.children:
            res = self._extract_receiver_type(child)
            if res:
                return res
        return ""

    def _resolve_call_target(self, node: Node) -> Optional[str]:
        func_node = node.child_by_field_name("function") or (node.children[0] if len(node.children) > 0 else None)
        if not func_node:
            return None
        return self._get_text(func_node)

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def visit_type_spec(self, node: Node):
        name_node = node.child_by_field_name("name")
        type_name = self._get_text(name_node) if name_node else "unknown"
        
        type_node = node.child_by_field_name("type")
        if type_node and type_node.type in ("struct_type", "interface_type"):
            class_id = f"{self.file_path}::{type_name}"
            if self.current_scope:
                class_id = f"{self.current_scope[-1]}.{type_name}"

            start_line = node.start_point[0] + 1
            end_line = node.end_point[0] + 1
            kind_lbl = "struct" if type_node.type == "struct_type" else "interface"

            self.collector.add_node(
                node_id=class_id,
                name=type_name,
                kind="CLASS",
                start_line=start_line,
                end_line=end_line,
                signature=f"type {type_name} {kind_lbl}"
            )

            if self.current_scope:
                self.collector.add_edge(self.current_scope[-1], class_id, "AST", label="CONTAINS")

            self.current_scope.append(class_id)
            
            # Recursive interface method specs query matching method_elem
            if type_node.type == "interface_type":
                def find_method_specs(n):
                    if n.type == "method_elem":
                        name_node = None
                        for c in n.children:
                            if c.type == "field_identifier":
                                name_node = c
                                break
                        if name_node:
                            m_name = self._get_text(name_node)
                            m_id = f"{class_id}.{m_name}"
                            self.collector.add_node(
                                node_id=m_id,
                                name=m_name,
                                kind="FUNCTION",
                                start_line=n.start_point[0] + 1,
                                end_line=n.end_point[0] + 1,
                                signature=self._get_text(n)
                            )
                            self.collector.add_edge(class_id, m_id, "AST", label="CONTAINS")
                    for child in n.children:
                        find_method_specs(child)
                find_method_specs(type_node)
            else:
                self.generic_visit(type_node)
                
            self.current_scope.pop()

    def visit_function_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        fn_name = self._get_text(name_node) if name_node else "unknown"
        
        fn_id = f"{self.file_path}::{fn_name}"
        if self.current_scope:
            fn_id = f"{self.current_scope[-1]}.{fn_name}"

        params = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            for child in param_list.children:
                if child.type == "parameter_declaration":
                    for sub in child.children:
                        if sub.type == "identifier":
                            params.append(self._get_text(sub))

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=fn_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"func {fn_name}({', '.join(params)})"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        self.scope_defs.append({param: {fn_id} for param in params})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        # Go Constructor mapping
        if fn_name.startswith("New") and self.db_path:
            result_node = node.child_by_field_name("result")
            if result_node:
                raw_result = self._get_text(result_node).strip("*& ")
                qualified_result = f"{self.package_name}.{raw_result}" if self.package_name else raw_result
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        INSERT OR IGNORE INTO instantiations (class_id, instantiation_type, file_path, line_number)
                        VALUES (?, 'NEW_EXPR', ?, ?)
                    """, (qualified_result, self.file_path, start_line))
                    conn.commit()

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_method_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        method_name = self._get_text(name_node) if name_node else "unknown"
        
        receiver_node = node.child_by_field_name("receiver")
        rec_type = "unknown"
        if receiver_node:
            rec_type = self._extract_receiver_type(receiver_node) or "unknown"
            
        fn_id = f"{self.file_path}::{rec_type}.{method_name}"

        # Get exact signature text
        param_list = node.child_by_field_name("parameters")
        param_text = self._get_text(param_list) if param_list else "()"
        
        result_node = node.child_by_field_name("result")
        result_text = self._get_text(result_node) if result_node else ""

        sig = f"func ({rec_type}) {method_name}{param_text}"
        if result_text:
            sig += f" {result_text}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=method_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=sig
        )

        struct_id = f"{self.file_path}::{rec_type}"
        self.collector.add_edge(struct_id, fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        
        params = []
        if param_list:
            for child in param_list.children:
                if child.type == "parameter_declaration":
                    for sub in child.children:
                        if sub.type == "identifier":
                            params.append(self._get_text(sub))
        self.scope_defs.append({param: {fn_id} for param in params})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_composite_literal(self, node: Node):
        type_node = node.child_by_field_name("type")
        if type_node and self.db_path:
            raw_type = self._get_text(type_node).strip("*& ")
            qualified_type = f"{self.package_name}.{raw_type}" if self.package_name else raw_type
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO instantiations (class_id, instantiation_type, file_path, line_number)
                    VALUES (?, 'NEW_EXPR', ?, ?)
                """, (qualified_type, self.file_path, node.start_point[0] + 1))
                conn.commit()
        self.generic_visit(node)

    def visit_short_var_declaration(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        stmt_id = f"{self.file_path}::L{start_line}_short_decl"
        
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")
        
        written_vars = self._extract_identifiers(left_node) if left_node else []
        
        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "short_decl",
            kind="ASSIGN",
            start_line=start_line,
            end_line=end_line,
            code=self._get_text(node)
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], stmt_id, "AST", label="CONTAINS")

        self._link_cfg(stmt_id)

        current_defs = self.scope_defs[-1]
        
        if right_node:
            for ident in self._extract_identifiers(right_node):
                if ident in current_defs:
                    for reaching_id in current_defs[ident]:
                        self.collector.add_edge(reaching_id, stmt_id, "DFG", label=ident)

        for var in written_vars:
            current_defs[var] = {stmt_id}
            self.collector.add_edge(stmt_id, stmt_id, "DFG", label=var)

        self.generic_visit(node)

    def visit_assignment_statement(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        stmt_id = f"{self.file_path}::L{start_line}_assign_stmt"
        
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")
        
        written_vars = self._extract_identifiers(left_node) if left_node else []
        
        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "assign_stmt",
            kind="ASSIGN",
            start_line=start_line,
            end_line=end_line,
            code=self._get_text(node)
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], stmt_id, "AST", label="CONTAINS")

        self._link_cfg(stmt_id)

        current_defs = self.scope_defs[-1]
        
        if right_node:
            for ident in self._extract_identifiers(right_node):
                if ident in current_defs:
                    for reaching_id in current_defs[ident]:
                        self.collector.add_edge(reaching_id, stmt_id, "DFG", label=ident)

        for var in written_vars:
            current_defs[var] = {stmt_id}
            self.collector.add_edge(stmt_id, stmt_id, "DFG", label=var)

        self.generic_visit(node)

    def visit_if_statement(self, node: Node):
        start_line = node.start_point[0] + 1
        
        cond_id = f"{self.file_path}::L{start_line}_if"
        
        cond_node = node.child_by_field_name("condition")
        cond_code = self._get_text(cond_node) if cond_node else ""
        
        self.collector.add_node(
            node_id=cond_id,
            name=cond_code,
            kind="BRANCH",
            start_line=start_line,
            end_line=start_line,
            code=f"if {cond_code}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], cond_id, "AST", label="CONTAINS")

        self._link_cfg(cond_id)
        base_defs = {k: set(v) for k, v in self.scope_defs[-1].items()}

        self.last_cfg_nodes = [cond_id]
        self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
        
        consequence = node.child_by_field_name("consequence")
        if consequence:
            conseq_id = f"{cond_id}::consequence"
            self.collector.add_node(
                node_id=conseq_id,
                name="consequence",
                kind="BRANCH_ARM",
                start_line=consequence.start_point[0] + 1,
                end_line=consequence.end_point[0] + 1,
                signature=""
            )
            self.collector.add_edge(cond_id, conseq_id, "AST", label="CONTAINS")
            self.current_scope.append(conseq_id)
            self.visit(consequence)
            self.current_scope.pop()
            
        true_exits = list(self.last_cfg_nodes)
        true_defs = self.scope_defs.pop()

        self.last_cfg_nodes = [cond_id]
        self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
        
        alternative = node.child_by_field_name("alternative")
        if alternative:
            alt_id = f"{cond_id}::alternative"
            self.collector.add_node(
                node_id=alt_id,
                name="alternative",
                kind="BRANCH_ARM",
                start_line=alternative.start_point[0] + 1,
                end_line=alternative.end_point[0] + 1,
                signature=""
            )
            self.collector.add_edge(cond_id, alt_id, "AST", label="CONTAINS")
            self.current_scope.append(alt_id)
            self.visit(alternative)
            self.current_scope.pop()
            
        false_exits = list(self.last_cfg_nodes)
        false_defs = self.scope_defs.pop()

        self.last_cfg_nodes = list(set(true_exits + false_exits))
        all_keys = set(base_defs.keys()) | set(true_defs.keys()) | set(false_defs.keys())
        merged: Dict[str, Set[str]] = {}

        for k in all_keys:
            t_set = true_defs.get(k, base_defs.get(k, set()))
            f_set = false_defs.get(k, base_defs.get(k, set()))
            merged[k] = t_set | f_set

        self.scope_defs[-1] = merged

    def visit_call_expression(self, node: Node):
        call_target = self._resolve_call_target(node)
        if call_target and self.current_scope:
            self.collector.add_edge(self.current_scope[-1], call_target, "CALLS", label="INVOKE")
        self.generic_visit(node)
