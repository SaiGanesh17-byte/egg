import sqlite3
from pathlib import Path
from tree_sitter import Node
from typing import List, Dict, Set, Optional
from .base_parser import BaseParser

class TypeScriptImportResolver:
    def __init__(self, file_path: str, imports: List[dict]):
        self.file_path = file_path
        self.imports = imports

    def resolve(self, class_name: str, defined_classes_in_repo: Set[str]) -> tuple:
        # 1. Resolve relative and absolute imports
        for imp in self.imports:
            if class_name in imp.get("named", []):
                source_val = imp["source"]
                source_filename = Path(source_val).name
                
                # Check for matching qualified name in defined classes
                for qid in defined_classes_in_repo:
                    if "::" in qid:
                        qpath, qname = qid.split("::", 1)
                        if qname == class_name:
                            if source_filename in qpath:
                                return qid, False

        # 2. Check same file declaration
        same_file_candidate = f"{self.file_path}::{class_name}"
        if same_file_candidate in defined_classes_in_repo:
            return same_file_candidate, False

        # 3. Fallback: match by class simple name globally
        matches = [qid for qid in defined_classes_in_repo if qid.split("::")[-1] == class_name]
        if len(matches) == 1:
            return matches[0], False
        elif len(matches) > 1:
            return sorted(matches), True

        return same_file_candidate, True


class TypeScriptParser(BaseParser):
    def __init__(self, file_path: str, source_code: str, collector, db_path: str = None, defined_classes: Set[str] = None):
        super().__init__(file_path, source_code, collector)
        self.db_path = db_path
        self.defined_classes = defined_classes or set()
        self.current_scope: List[str] = []
        self.scope_defs: List[Dict[str, Set[str]]] = [{}]
        self.last_cfg_nodes: List[str] = []
        self.class_stack: List[str] = []
        self.import_resolver = None

    @staticmethod
    def discover_namespace(file_path: str, source_code: str, tree) -> List[tuple]:
        results = []
        source_bytes = source_code.encode("utf-8")
        
        # Walks nodes to find top-level and nested classes/interfaces
        def walk(n):
            if n.type in ("class_declaration", "interface_declaration"):
                name_node = n.child_by_field_name("name")
                if name_node:
                    simple_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                    qualified_name = f"{file_path}::{simple_name}"
                    results.append((qualified_name, "CLASS"))
            # Skip block statement bodies during namespace discovery
            if n.type == "statement_block":
                return
            for c in n.children:
                walk(c)
        walk(tree.root_node)
        return results

    def parse(self, root_node: Node):
        # 1. Parse import statements to build TypeScriptImportResolver
        imports = []
        for child in root_node.children:
            if child.type == "import_statement":
                # Matches: import { A, B } from 'source'; or import Default from 'source';
                clause = child.child_by_field_name("clause")
                source_node = child.child_by_field_name("source")
                if source_node:
                    source_val = self._get_text(source_node).strip("'\"")
                    named_imports = []
                    
                    if clause:
                        # Check named_imports inside clause
                        named_node = clause.child_by_field_name("named_imports")
                        if named_node:
                            for spec in named_node.children:
                                if spec.type == "import_specifier":
                                    name_node = spec.child_by_field_name("name")
                                    if name_node:
                                        named_imports.append(self._get_text(name_node))
                        else:
                            # Default import
                            name_node = clause.child_by_field_name("name")
                            if name_node:
                                named_imports.append(self._get_text(name_node))
                    
                    imports.append({
                        "named": named_imports,
                        "source": source_val
                    })
                    
        self.import_resolver = TypeScriptImportResolver(self.file_path, imports)
        self.visit(root_node)

    def _extract_identifiers(self, node: Node) -> List[str]:
        if node is None:
            return []
        ids = []
        if node.type == "identifier":
            ids.append(self._get_text(node))
        elif node.type == "property_identifier":
            ids.append(self._get_text(node))
        elif node.type == "member_expression":
            ids.append(self._get_text(node))
        else:
            for child in node.children:
                ids.extend(self._extract_identifiers(child))
        return ids

    def _resolve_call_target(self, node: Node) -> Optional[str]:
        func_node = node.child_by_field_name("function") or (node.children[0] if len(node.children) > 0 else None)
        if not func_node:
            return None
        raw_target = self._get_text(func_node)
        
        if raw_target.startswith("this.") and self.class_stack:
            method_name = raw_target.split("this.", 1)[1]
            enclosing_class = self.class_stack[-1]
            return f"{self.file_path}::{enclosing_class}.{method_name}"
            
        return raw_target

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def _extract_decorators(self, node: Node) -> List[str]:
        decorators = []
        for child in node.children:
            if child.type == "decorator":
                # Decorator wraps identifier or call_expression
                for desc in child.children:
                    if desc.type == "identifier":
                        decorators.append(self._get_text(desc))
                    elif desc.type == "call_expression":
                        func_node = desc.child_by_field_name("function")
                        if func_node:
                            decorators.append(self._get_text(func_node))
        return decorators

    def visit_class_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        class_name = self._get_text(name_node) if name_node else "unknown"
        
        class_id = f"{self.file_path}::{class_name}"
        if self.current_scope:
            class_id = f"{self.current_scope[-1]}.{class_name}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=class_id,
            name=class_name,
            kind="CLASS",
            start_line=start_line,
            end_line=end_line,
            signature=f"class {class_name}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], class_id, "AST", label="CONTAINS")

        self.current_scope.append(class_id)
        self.class_stack.append(class_name)

        # 1. Extends class heritage
        heritage = node.child_by_field_name("heritage")
        if heritage and self.db_path and self.import_resolver:
            for child in heritage.children:
                if child.type == "extends_clause":
                    val_node = child.child_by_field_name("value")
                    if val_node:
                        parent_name = self._get_text(val_node)
                        resolved, is_unqualified = self.import_resolver.resolve(parent_name, self.defined_classes)
                        resolved_list = resolved if isinstance(resolved, list) else [resolved]
                        with sqlite3.connect(self.db_path) as conn:
                            cur = conn.cursor()
                            for candidate in resolved_list:
                                cur.execute("""
                                    INSERT OR IGNORE INTO class_hierarchy (child_id, parent_id, relation_type, unqualified)
                                    VALUES (?, ?, 'EXTENDS', ?)
                                """, (class_id, candidate, int(is_unqualified)))
                            conn.commit()

        # 2. DI Decorator Instantiations (NestJS style Injectable)
        decorators = self._extract_decorators(node)
        if "Injectable" in decorators and self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO instantiations (class_id, instantiation_type, file_path, line_number)
                    VALUES (?, 'DI_ANNOTATION', ?, ?)
                """, (class_id, self.file_path, start_line))
                conn.commit()

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.class_stack.pop()
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
                if child.type == "identifier":
                    params.append(self._get_text(child))
                elif child.type in ("required_parameter", "optional_parameter"):
                    for sub in child.children:
                        if sub.type == "identifier":
                            params.append(self._get_text(sub))
                            break

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=fn_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"function {fn_name}({', '.join(params)})"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        self.scope_defs.append({param: {fn_id} for param in params})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_method_definition(self, node: Node):
        name_node = node.child_by_field_name("name")
        method_name = self._get_text(name_node) if name_node else "unknown"
        
        fn_id = f"{self.file_path}::{method_name}"
        if self.current_scope:
            fn_id = f"{self.current_scope[-1]}.{method_name}"

        params = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            for child in param_list.children:
                if child.type == "identifier":
                    params.append(self._get_text(child))

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=method_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"method {method_name}({', '.join(params)})"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        self.scope_defs.append({param: {fn_id} for param in params})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_new_expression(self, node: Node):
        constructor_node = node.child_by_field_name("constructor")
        if constructor_node:
            raw_type = self._get_text(constructor_node)
            if self.db_path and self.import_resolver:
                resolved, _ = self.import_resolver.resolve(raw_type, self.defined_classes)
                resolved_list = resolved if isinstance(resolved, list) else [resolved]
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    for candidate in resolved_list:
                        cur.execute("""
                            INSERT OR IGNORE INTO instantiations (class_id, instantiation_type, file_path, line_number)
                            VALUES (?, 'NEW_EXPR', ?, ?)
                        """, (candidate, self.file_path, node.start_point[0] + 1))
                    conn.commit()
        self.generic_visit(node)

    def visit_arrow_function(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        fn_name = f"arrow_L{start_line}"
        fn_id = f"{self.file_path}::{fn_name}"
        if self.current_scope:
            fn_id = f"{self.current_scope[-1]}.{fn_name}"

        params = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            for child in param_list.children:
                if child.type == "identifier":
                    params.append(self._get_text(child))

        self.collector.add_node(
            node_id=fn_id,
            name=fn_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"arrow {fn_name}({', '.join(params)})"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        self.scope_defs.append({param: {fn_id} for param in params})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_variable_declarator(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        stmt_id = f"{self.file_path}::L{start_line}_var_assign"
        
        name_node = node.child_by_field_name("name")
        value_node = node.child_by_field_name("value")
        
        written_vars = self._extract_identifiers(name_node) if name_node else []
        
        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "var_assign",
            kind="ASSIGN",
            start_line=start_line,
            end_line=end_line,
            code=self._get_text(node)
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], stmt_id, "AST", label="CONTAINS")

        self._link_cfg(stmt_id)

        current_defs = self.scope_defs[-1]
        
        if value_node:
            for ident in self._extract_identifiers(value_node):
                if ident in current_defs:
                    for reaching_id in current_defs[ident]:
                        self.collector.add_edge(reaching_id, stmt_id, "DFG", label=ident)

        for var in written_vars:
            current_defs[var] = {stmt_id}
            self.collector.add_edge(stmt_id, stmt_id, "DFG", label=var)

        self.generic_visit(node)

    def visit_assignment_expression(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        stmt_id = f"{self.file_path}::L{start_line}_assign_expr"
        
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")
        
        written_vars = self._extract_identifiers(left_node) if left_node else []
        
        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "assign_expr",
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
            code=f"if ({cond_code})"
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
