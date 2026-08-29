import sqlite3
import re
from tree_sitter import Node
from typing import List, Dict, Set, Optional
from .base_parser import BaseParser

JAVA_LANG_IMPLICIT = {
    "Object", "Class", "String", "StringBuilder", "StringBuffer", "System",
    "Math", "Number", "Integer", "Double", "Float", "Long", "Short", "Byte",
    "Boolean", "Character", "Thread", "ThreadGroup", "Throwable", "Exception",
    "RuntimeException", "Error", "StackTraceElement", "Void", "Process",
    "Runtime", "ClassLoader", "Enum", "Record",
    "Runnable", "Comparable", "Iterable", "Cloneable", "AutoCloseable",
    "CharSequence", "Readable", "Appendable"
}

class JavaImportResolver:
    def __init__(self, package_name: str, imports: List[str]):
        self.package_name = package_name
        self.explicit_imports = {}
        self.wildcard_imports = ["java.lang"]
        
        for imp in imports:
            if imp.endswith(".*"):
                self.wildcard_imports.append(imp[:-2])
            else:
                simple_name = imp.split(".")[-1]
                self.explicit_imports[simple_name] = imp

    def resolve(self, class_name: str, defined_classes_in_repo: Set[str]) -> tuple:
        if "." in class_name:
            return class_name, False
            
        if class_name in self.explicit_imports:
            return self.explicit_imports[class_name], False
            
        same_pkg_candidate = f"{self.package_name}.{class_name}" if self.package_name else class_name
        if same_pkg_candidate in defined_classes_in_repo:
            return same_pkg_candidate, False

        # Implicit java.lang types check (placed after same-pkg to allow shadowing, but before wildcards)
        # Note: Checked against JDK 21. Review/extend if target JDK version changes.
        if class_name in JAVA_LANG_IMPLICIT:
            return f"java.lang.{class_name}", False
            
        wildcard_matches = []
        for wildcard in self.wildcard_imports:
            candidate = f"{wildcard}.{class_name}"
            if candidate in defined_classes_in_repo:
                wildcard_matches.append(candidate)
                
        if len(wildcard_matches) == 1:
            return wildcard_matches[0], False
        elif len(wildcard_matches) > 1:
            return wildcard_matches, True
            
        # Fallback: match by simple name globally across discovered classes
        global_matches = [qid for qid in defined_classes_in_repo if qid.split(".")[-1] == class_name]
        if len(global_matches) == 1:
            return global_matches[0], True
        elif len(global_matches) > 1:
            return sorted(global_matches), True

        return same_pkg_candidate, True


class JavaParser(BaseParser):
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
        package_name = ""
        results = []
        class_path_stack: List[str] = []
        source_bytes = source_code.encode("utf-8")

        DECL_KINDS = {
            "class_declaration": "CLASS",
            "interface_declaration": "INTERFACE",
            "enum_declaration": "ENUM",
            "record_declaration": "RECORD",
            "annotation_type_declaration": "ANNOTATION",
        }

        # First extract package name
        for child in tree.root_node.children:
            if child.type == "package_declaration":
                # Find scoped_identifier or identifier child
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        package_name = source_bytes[sub.start_byte:sub.end_byte].decode("utf-8", errors="ignore").strip()
                        break
                break

        def walk(node):
            kind = DECL_KINDS.get(node.type)
            if kind:
                name_node = node.child_by_field_name("name")
                if name_node:
                    simple_name = source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore").strip()
                    
                    prefix = ".".join([package_name] + class_path_stack) if package_name else ".".join(class_path_stack)
                    qualified_name = f"{prefix}.{simple_name}" if prefix else simple_name
                    
                    results.append((qualified_name, kind))
                    class_path_stack.append(simple_name)
                    
                    for c in node.children:
                        walk(c)
                    
                    class_path_stack.pop()
            else:
                # Skip method/constructor bodies during Pass 1 discovery
                if node.type == "block":
                    return
                for c in node.children:
                    walk(c)

        walk(tree.root_node)
        return results

    def parse(self, root_node: Node):
        # 1. Extract package and imports to build JavaImportResolver
        package_name = ""
        imports = []
        for child in root_node.children:
            if child.type == "package_declaration":
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        package_name = self._get_text(sub).strip()
                        break
            elif child.type == "import_declaration":
                imp_text = self._get_text(child).strip()
                imp_text = imp_text.replace("import", "").replace("static", "").replace(";", "").strip()
                imports.append(imp_text)
                
        self.import_resolver = JavaImportResolver(package_name, imports)
        self.visit(root_node)

    def _extract_identifiers(self, node: Node) -> List[str]:
        if node is None:
            return []
        ids = []
        if node.type == "identifier":
            ids.append(self._get_text(node))
        elif node.type == "field_access":
            ids.append(self._get_text(node))
        else:
            for child in node.children:
                ids.extend(self._extract_identifiers(child))
        return ids

    def _extract_formal_parameter_types(self, node: Node) -> List[str]:
        types = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            for child in param_list.children:
                if child.type == "formal_parameter":
                    t_node = child.child_by_field_name("type")
                    if t_node:
                        t_text = self._get_text(t_node).strip()
                        types.append(t_text)
        return types

    def _extract_formal_parameter_names(self, node: Node) -> List[str]:
        names = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            for child in param_list.children:
                if child.type == "formal_parameter":
                    n_node = child.child_by_field_name("name")
                    if n_node:
                        names.append(self._get_text(n_node).strip())
        return names

    def _resolve_call_target(self, node: Node) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return None
        return self._get_text(name_node)

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def _extract_base_type_name(self, type_node: Node) -> str:
        if type_node.type == "generic_type":
            base_node = type_node.child_by_field_name("type")
            if base_node:
                return self._get_text(base_node)
        elif type_node.type == "array_type":
            elem_node = type_node.child_by_field_name("element")
            if elem_node:
                return self._extract_base_type_name(elem_node)
        return self._get_text(type_node)

    def _extract_annotations(self, modifiers_node) -> List[str]:
        if not modifiers_node:
            return []
        annos = []
        for child in modifiers_node.children:
            if child.type in ("annotation", "marker_annotation"):
                name_node = child.child_by_field_name("name")
                if name_node:
                    anno_name = self._get_text(name_node).split(".")[-1]
                    annos.append(anno_name)
        return annos

    def _write_hierarchy_row(self, child_id: str, parent_name: str, relation_type: str, line_number: int):
        if not self.db_path or not self.import_resolver:
            return
        resolved, is_unqualified = self.import_resolver.resolve(parent_name, self.defined_classes)
        resolved_list = resolved if isinstance(resolved, list) else [resolved]
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            for candidate in resolved_list:
                cur.execute("""
                    INSERT OR IGNORE INTO class_hierarchy (child_id, parent_id, relation_type, unqualified)
                    VALUES (?, ?, ?, ?)
                """, (child_id, candidate, relation_type, int(is_unqualified)))
            conn.commit()

    def visit_class_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        class_name = self._get_text(name_node) if name_node else "unknown"
        
        class_id = f"{self.file_path}::{class_name}"
        if self.current_scope:
            parent_scope = self.current_scope[-1]
            class_id = f"{parent_scope}.{class_name}"

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

        pkg_prefix = self.import_resolver.package_name if self.import_resolver else ""
        resolved_class_path = ".".join([pkg_prefix] + self.class_stack) if pkg_prefix else ".".join(self.class_stack)

        # 1. Extends superclass (using robust type matching)
        superclass_node = None
        for child in node.children:
            if child.type == "superclass":
                superclass_node = child
                break
        if superclass_node:
            def find_types(n, parent_is_type=False):
                is_type = n.type in ("type_identifier", "scoped_type_identifier", "generic_type")
                if is_type and not parent_is_type:
                    p_name = self._extract_base_type_name(n)
                    self._write_hierarchy_row(resolved_class_path, p_name, "EXTENDS", start_line)
                for child in n.children:
                    find_types(child, parent_is_type=is_type or parent_is_type)
            find_types(superclass_node)

        # 2. Implements interfaces (using robust type matching)
        interfaces_node = None
        for child in node.children:
            if child.type == "super_interfaces":
                interfaces_node = child
                break
        if interfaces_node:
            def find_types(n, parent_is_type=False):
                is_type = n.type in ("type_identifier", "scoped_type_identifier", "generic_type")
                if is_type and not parent_is_type:
                    p_name = self._extract_base_type_name(n)
                    self._write_hierarchy_row(resolved_class_path, p_name, "IMPLEMENTS", start_line)
                for child in n.children:
                    find_types(child, parent_is_type=is_type or parent_is_type)
            find_types(interfaces_node)

        # 3. Class-level DI Bean Instantiations
        modifiers = node.child_by_field_name("modifiers")
        annos = self._extract_annotations(modifiers)
        di_annotation_kinds = {"Component", "Service", "Repository", "Controller"}
        if any(a in di_annotation_kinds for a in annos) and self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.cursor()
                cur.execute("""
                    INSERT OR IGNORE INTO instantiations (class_id, instantiation_type, file_path, line_number)
                    VALUES (?, 'DI_ANNOTATION', ?, ?)
                """, (resolved_class_path, self.file_path, start_line))
                conn.commit()

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.class_stack.pop()
        self.current_scope.pop()

    def visit_interface_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        interface_name = self._get_text(name_node) if name_node else "unknown"
        
        interface_id = f"{self.file_path}::{interface_name}"
        if self.current_scope:
            interface_id = f"{self.current_scope[-1]}.{interface_name}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=interface_id,
            name=interface_name,
            kind="CLASS",
            start_line=start_line,
            end_line=end_line,
            signature=f"interface {interface_name}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], interface_id, "AST", label="CONTAINS")

        self.current_scope.append(interface_id)
        self.class_stack.append(interface_name)

        pkg_prefix = self.import_resolver.package_name if self.import_resolver else ""
        resolved_iface_path = ".".join([pkg_prefix] + self.class_stack) if pkg_prefix else ".".join(self.class_stack)

        interfaces_node = None
        for child in node.children:
            if child.type == "super_interfaces":
                interfaces_node = child
                break
        if interfaces_node:
            def find_types(n, parent_is_type=False):
                is_type = n.type in ("type_identifier", "scoped_type_identifier", "generic_type")
                if is_type and not parent_is_type:
                    p_name = self._extract_base_type_name(n)
                    self._write_hierarchy_row(resolved_iface_path, p_name, "IMPLEMENTS", start_line)
                for child in n.children:
                    find_types(child, parent_is_type=is_type or parent_is_type)
            find_types(interfaces_node)

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.class_stack.pop()
        self.current_scope.pop()

    def visit_method_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        method_name = self._get_text(name_node) if name_node else "unknown"
        
        param_types = self._extract_formal_parameter_types(node)
        sig_suffix = f"({','.join(param_types)})"
        
        class_name = self.class_stack[-1] if self.class_stack else ""
        
        if class_name:
            fn_id = f"{self.file_path}::{class_name}.{method_name}{sig_suffix}"
        else:
            fn_id = f"{self.file_path}::{method_name}{sig_suffix}"
            if self.current_scope:
                fn_id = f"{self.current_scope[-1]}.{method_name}{sig_suffix}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=method_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"{method_name}{sig_suffix}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        param_names = self._extract_formal_parameter_names(node)
        self.scope_defs.append({param: {fn_id} for param in param_names})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        modifiers = node.child_by_field_name("modifiers")
        annos = self._extract_annotations(modifiers)
        if "Bean" in annos and self.db_path:
            type_node = node.child_by_field_name("type")
            if type_node:
                raw_type = self._extract_base_type_name(type_node)
                resolved, _ = self.import_resolver.resolve(raw_type, self.defined_classes)
                resolved_list = resolved if isinstance(resolved, list) else [resolved]
                with sqlite3.connect(self.db_path) as conn:
                    cur = conn.cursor()
                    for candidate in resolved_list:
                        cur.execute("""
                            INSERT OR IGNORE INTO instantiations (class_id, instantiation_type, file_path, line_number)
                            VALUES (?, 'DI_ANNOTATION', ?, ?)
                        """, (candidate, self.file_path, start_line))
                    conn.commit()

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_constructor_declaration(self, node: Node):
        name_node = node.child_by_field_name("name")
        const_name = self._get_text(name_node) if name_node else "Constructor"
        
        param_types = self._extract_formal_parameter_types(node)
        sig_suffix = f"({','.join(param_types)})"
        
        class_name = self.class_stack[-1] if self.class_stack else const_name
        fn_id = f"{self.file_path}::{class_name}.{const_name}{sig_suffix}"

        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1

        self.collector.add_node(
            node_id=fn_id,
            name=const_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"new {const_name}{sig_suffix}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        param_names = self._extract_formal_parameter_names(node)
        self.scope_defs.append({param: {fn_id} for param in param_names})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_object_creation_expression(self, node: Node):
        type_node = node.child_by_field_name("type")
        if type_node:
            raw_type = self._extract_base_type_name(type_node)
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

    def _infer_java_receiver_type(self, code: str, receiver_name: str, enclosing_class: str) -> str:
        if receiver_name == "this" or receiver_name == "super":
            return enclosing_class
        # Check local variable declarations
        pat = re.compile(r"\b([A-Za-z0-9_]+)\s+" + re.escape(receiver_name) + r"\b")
        m = pat.search(code)
        if m:
            return m.group(1)
        # Check if receiver name itself starts with uppercase (static method call on a Class)
        if receiver_name and receiver_name[0].isupper() and "." not in receiver_name:
            return receiver_name
        return receiver_name

    def visit_method_invocation(self, node: Node):
        method_name = self._resolve_call_target(node)
        if method_name and self.current_scope:
            receiver_node = node.child_by_field_name("object")
            enclosing_class = self.class_stack[-1] if self.class_stack else ""
            
            # Default fallback target
            call_target = method_name
            
            # Infer receiver type if dot notation is used
            if receiver_node:
                receiver_name = self._get_text(receiver_node).strip()
                parent = node.parent
                while parent and parent.type not in ("method_declaration", "constructor_declaration"):
                    parent = parent.parent
                
                if parent:
                    method_code = self._get_text(parent)
                    receiver_type = self._infer_java_receiver_type(method_code, receiver_name, enclosing_class)
                    if self.import_resolver:
                        resolved, _ = self.import_resolver.resolve(receiver_type, self.defined_classes)
                        resolved_class = resolved[0] if isinstance(resolved, list) and resolved else resolved
                        if resolved_class:
                            call_target = f"{resolved_class}.{method_name}"
            else:
                if enclosing_class:
                    if self.import_resolver:
                        resolved, _ = self.import_resolver.resolve(enclosing_class, self.defined_classes)
                        resolved_class = resolved[0] if isinstance(resolved, list) and resolved else resolved
                        if resolved_class:
                            call_target = f"{resolved_class}.{method_name}"
                        else:
                            call_target = f"{enclosing_class}.{method_name}"
                    else:
                        call_target = f"{enclosing_class}.{method_name}"
            
            self.collector.add_edge(self.current_scope[-1], call_target, "CALLS", label="INVOKE")
        self.generic_visit(node)

    def visit_lambda_expression(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        fn_name = f"lambda_L{start_line}"
        fn_id = f"{self.file_path}::{fn_name}"
        if self.current_scope:
            fn_id = f"{self.current_scope[-1]}.{fn_name}"

        params = []
        param_list = node.child_by_field_name("parameters")
        if param_list:
            if param_list.type == "identifier":
                params.append(self._get_text(param_list))
            elif param_list.type == "formal_parameters":
                for child in param_list.children:
                    if child.type == "formal_parameter":
                        n_node = child.child_by_field_name("name")
                        if n_node:
                            params.append(self._get_text(n_node).strip())
            elif param_list.type == "inferred_parameters":
                for child in param_list.children:
                    if child.type == "identifier":
                        params.append(self._get_text(child))

        self.collector.add_node(
            node_id=fn_id,
            name=fn_name,
            kind="FUNCTION",
            start_line=start_line,
            end_line=end_line,
            signature=f"lambda {fn_name}({', '.join(params)})"
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
