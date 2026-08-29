import sqlite3
from pathlib import Path
from tree_sitter import Node
from typing import List, Dict, Set, Optional
from .base_parser import BaseParser

class RustImportResolver:
    def __init__(self, crate_prefix: str, imports: List[str]):
        self.crate_prefix = crate_prefix
        self.imports = imports

    def resolve(self, class_name: str, defined_classes_in_repo: Set[str]) -> tuple:
        # Resolve imports matching the class name
        for imp in self.imports:
            if class_name in imp or imp.endswith(f"::{class_name}"):
                for qid in defined_classes_in_repo:
                    if "::" in qid:
                        qname = qid.split("::")[-1]
                        if qname == class_name:
                            return qid, False
                                
        # Check same file / local crate module declaration
        for qid in defined_classes_in_repo:
            if qid.endswith(f"::{class_name}"):
                # Prioritize local module path matching our crate prefix
                if qid.startswith(self.crate_prefix):
                    return qid, False

        # Fallback: match by simple name globally
        matches = [qid for qid in defined_classes_in_repo if qid.split("::")[-1] == class_name]
        if len(matches) == 1:
            return matches[0], False
        elif len(matches) > 1:
            return sorted(matches), True

        return f"{self.crate_prefix}::{class_name}", True


class RustParser(BaseParser):
    def __init__(self, file_path: str, source_code: str, collector, db_path: str = None, defined_classes: Set[str] = None):
        super().__init__(file_path, source_code, collector)
        self.db_path = db_path
        self.defined_classes = defined_classes or set()
        self.current_scope: List[str] = []
        self.scope_defs: List[Dict[str, Set[str]]] = [{}]
        self.last_cfg_nodes: List[str] = []
        self.current_struct: Optional[str] = None
        self.import_resolver = None

        # Calculate Rust module qualification crate prefix (e.g. src/foo/bar.rs -> crate::foo::bar)
        path_obj = Path(file_path)
        parts = list(path_obj.with_suffix("").parts)
        if parts and parts[0] == "src":
            parts[0] = "crate"
        if parts and parts[-1] in ("lib", "main", "mod"):
            parts.pop()
        self.crate_prefix = "::".join(parts) if parts else "crate"

    @staticmethod
    def discover_namespace(file_path: str, source_code: str, tree) -> List[tuple]:
        path_obj = Path(file_path)
        parts = list(path_obj.with_suffix("").parts)
        if parts and parts[0] == "src":
            parts[0] = "crate"
        if parts and parts[-1] in ("lib", "main", "mod"):
            parts.pop()
        crate_prefix = "::".join(parts) if parts else "crate"

        results = []
        class_path_stack: List[str] = []
        source_bytes = source_code.encode("utf-8")
        
        def walk(n):
            if n.type in ("struct_item", "enum_item", "trait_item"):
                name_node = n.child_by_field_name("name")
                if name_node:
                    simple_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                    prefix = "::".join(class_path_stack)
                    
                    if prefix:
                        qualified_name = f"{crate_prefix}::{prefix}::{simple_name}"
                    else:
                        qualified_name = f"{crate_prefix}::{simple_name}"
                    results.append((qualified_name, "CLASS"))
            elif n.type == "mod_item":
                name_node = n.child_by_field_name("name")
                if name_node:
                    mod_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                    class_path_stack.append(mod_name)
                    body = n.child_by_field_name("body")
                    if body:
                        for c in body.children:
                            walk(c)
                    class_path_stack.pop()
                    return
            
            if n.type == "block":
                return
            for c in n.children:
                walk(c)
        walk(tree.root_node)
        return results

    def parse(self, root_node: Node):
        # Extract use statements for import resolver
        imports = []
        for child in root_node.children:
            if child.type == "use_declaration":
                argument = child.child_by_field_name("argument")
                if argument:
                    imp_text = self._get_text(argument).strip()
                    imports.append(imp_text)
                    
        self.import_resolver = RustImportResolver(self.crate_prefix, imports)
        self.visit(root_node)

    def _extract_identifiers(self, node: Node) -> List[str]:
        if node is None:
            return []
        ids = []
        if node.type == "identifier":
            ids.append(self._get_text(node))
        elif node.type == "field_expression":
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
        
        if raw_target.startswith("self.") and self.current_struct:
            method_name = raw_target.split("self.", 1)[1]
            return f"{self.crate_prefix}::{self.current_struct}.{method_name}"
            
        return raw_target

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def visit_struct_item(self, node: Node):
        name_node = node.child_by_field_name("name")
        struct_name = self._get_text(name_node) if name_node else "unknown"
        
        struct_id = f"{self.crate_prefix}::{struct_name}"
        if self.current_scope:
            struct_id = f"{self.current_scope[-1]}::{struct_name}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=struct_id,
            name=struct_name,
            kind="CLASS",
            start_line=start_line,
            end_line=end_line,
            signature=f"struct {struct_name}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], struct_id, "AST", label="CONTAINS")

        self.current_scope.append(struct_id)
        
        for child in node.children:
            if child.type in ("field_declaration_list", "ordered_field_declaration_list"):
                self.visit(child)
                
        self.current_scope.pop()

    def visit_enum_item(self, node: Node):
        name_node = node.child_by_field_name("name")
        enum_name = self._get_text(name_node) if name_node else "unknown"
        
        enum_id = f"{self.crate_prefix}::{enum_name}"
        if self.current_scope:
            enum_id = f"{self.current_scope[-1]}::{enum_name}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=enum_id,
            name=enum_name,
            kind="CLASS",
            start_line=start_line,
            end_line=end_line,
            signature=f"enum {enum_name}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], enum_id, "AST", label="CONTAINS")

        self.current_scope.append(enum_id)
        self.generic_visit(node)
        self.current_scope.pop()

    def visit_impl_item(self, node: Node):
        type_node = node.child_by_field_name("type")
        trait_node = node.child_by_field_name("trait")
        
        struct_name = "unknown"
        if type_node:
            struct_name = self._get_text(type_node)
            if "<" in struct_name:
                struct_name = struct_name.split("<")[0].strip()

        # Handle Trait implements mapping: impl Trait for Struct
        if trait_node and type_node and self.db_path and self.import_resolver:
            trait_name = self._get_text(trait_node)
            resolved_struct, struct_unqualified = self.import_resolver.resolve(struct_name, self.defined_classes)
            resolved_trait, trait_unqualified = self.import_resolver.resolve(trait_name, self.defined_classes)
            
            struct_list = resolved_struct if isinstance(resolved_struct, list) else [resolved_struct]
            trait_list = resolved_trait if isinstance(resolved_trait, list) else [resolved_trait]
            
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                for s in struct_list:
                    for t in trait_list:
                        cur.execute("""
                            INSERT OR IGNORE INTO class_hierarchy (child_id, parent_id, relation_type, unqualified)
                            VALUES (?, ?, 'IMPLEMENTS', ?)
                        """, (s, t, int(struct_unqualified or trait_unqualified)))
                conn.commit()

        old_struct = self.current_struct
        self.current_struct = struct_name

        body = node.child_by_field_name("body") or node
        self.generic_visit(body)

        self.current_struct = old_struct

    def visit_function_item(self, node: Node):
        name_node = node.child_by_field_name("name")
        fn_name = self._get_text(name_node) if name_node else "unknown"
        
        if self.current_struct:
            fn_id = f"{self.crate_prefix}::{self.current_struct}.{fn_name}"
        else:
            fn_id = f"{self.crate_prefix}::{fn_name}"
            if self.current_scope:
                fn_id = f"{self.current_scope[-1]}.{fn_name}"

        params = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            for child in param_list.children:
                if child.type in ("parameter", "self_parameter"):
                    params.append(self._get_text(child))

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=fn_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"fn {fn_name}({', '.join(params)})"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")
        elif self.current_struct:
            struct_id = f"{self.crate_prefix}::{self.current_struct}"
            self.collector.add_edge(struct_id, fn_id, "AST", label="CONTAINS")

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

    def visit_struct_expression(self, node: Node):
        name_node = node.child_by_field_name("name")
        if name_node and self.db_path and self.import_resolver:
            raw_type = self._get_text(name_node)
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

    def visit_call_expression(self, node: Node):
        call_target = self._resolve_call_target(node)
        if call_target and "::new" in call_target and self.db_path and self.import_resolver:
            raw_type = call_target.split("::new")[0].split("::")[-1]
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
                
        if call_target and self.current_scope:
            self.collector.add_edge(self.current_scope[-1], call_target, "CALLS", label="INVOKE")
        self.generic_visit(node)

    def visit_let_declaration(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        stmt_id = f"{self.crate_prefix}::L{start_line}_let"
        
        pattern_node = node.child_by_field_name("pattern")
        value_node = node.child_by_field_name("value")
        
        written_vars = self._extract_identifiers(pattern_node) if pattern_node else []
        
        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "let",
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
        
        stmt_id = f"{self.crate_prefix}::L{start_line}_assign_expr"
        
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

    def visit_if_expression(self, node: Node):
        start_line = node.start_point[0] + 1
        
        cond_id = f"{self.crate_prefix}::L{start_line}_if"
        
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

    def visit_match_expression(self, node: Node):
        start_line = node.start_point[0] + 1
        
        cond_id = f"{self.crate_prefix}::L{start_line}_match"
        
        value_node = node.child_by_field_name("value")
        match_value = self._get_text(value_node) if value_node else ""
        
        self.collector.add_node(
            node_id=cond_id,
            name=match_value,
            kind="BRANCH",
            start_line=start_line,
            end_line=start_line,
            code=f"match {match_value}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], cond_id, "AST", label="CONTAINS")

        self._link_cfg(cond_id)
        base_defs = {k: set(v) for k, v in self.scope_defs[-1].items()}

        exits = []
        arm_defs_list = []
        
        body = node.children[-1]
        if body and body.type == "match_block":
            for idx, arm in enumerate(body.children):
                if arm.type == "match_arm":
                    arm_id = f"{cond_id}::arm_{idx}"
                    self.collector.add_node(
                        node_id=arm_id,
                        name=f"arm_{idx}",
                        kind="BRANCH_ARM",
                        start_line=arm.start_point[0] + 1,
                        end_line=arm.end_point[0] + 1,
                        signature=""
                    )
                    self.collector.add_edge(cond_id, arm_id, "AST", label="CONTAINS")
                    
                    self.last_cfg_nodes = [cond_id]
                    self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
                    self.current_scope.append(arm_id)
                    self.visit(arm)
                    self.current_scope.pop()
                    exits.extend(self.last_cfg_nodes)
                    arm_defs_list.append(self.scope_defs.pop())

        if arm_defs_list:
            self.last_cfg_nodes = list(set(exits))
            all_keys = set(base_defs.keys())
            for d in arm_defs_list:
                all_keys |= d.keys()
                
            merged: Dict[str, Set[str]] = {}
            for k in all_keys:
                k_set = set()
                for d in arm_defs_list:
                    k_set |= d.get(k, base_defs.get(k, set()))
                merged[k] = k_set
            self.scope_defs[-1] = merged
