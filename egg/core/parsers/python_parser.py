from tree_sitter import Node
from typing import List, Dict, Set, Optional
from .base_parser import BaseParser

class PythonParser(BaseParser):
    def __init__(self, file_path: str, source_code: str, collector):
        super().__init__(file_path, source_code, collector)
        self.current_scope: List[str] = []
        self.scope_defs: List[Dict[str, Set[str]]] = [{}]
        self.last_cfg_nodes: List[str] = []
        self.class_stack: List[str] = []

    def parse(self, root_node: Node):
        self.visit(root_node)

    def _extract_identifiers(self, node: Node) -> List[str]:
        if node is None:
            return []
        ids = []
        if node.type == "identifier":
            ids.append(self._get_text(node))
        elif node.type == "attribute":
            ids.append(self._get_text(node))
        else:
            for child in node.children:
                ids.extend(self._extract_identifiers(child))
        return ids

    def _resolve_call_target(self, node: Node) -> Optional[str]:
        func_node = node.child_by_field_name("function")
        if not func_node:
            return None
        raw_target = self._get_text(func_node)
        
        if raw_target.startswith("self.") and self.class_stack:
            method_name = raw_target.split("self.", 1)[1]
            enclosing_class = self.class_stack[-1]
            return f"{self.file_path}::{enclosing_class}.{method_name}"
            
        return raw_target

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def visit_class_definition(self, node: Node):
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

        body = node.child_by_field_name("body")
        if body:
            self.visit(body)

        self.class_stack.pop()
        self.current_scope.pop()

    def visit_function_definition(self, node: Node):
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
                elif child.type in ("typed_parameter", "default_parameter"):
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
            signature=f"def {fn_name}({', '.join(params)})"
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

    def visit_assignment(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        stmt_id = f"{self.file_path}::L{start_line}_assign"
        
        left_node = node.child_by_field_name("left")
        right_node = node.child_by_field_name("right")
        
        written_vars = self._extract_identifiers(left_node) if left_node else []
        
        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "assign",
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
            code=f"if {cond_code}:"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], cond_id, "AST", label="CONTAINS")

        self._link_cfg(cond_id)
        base_defs = {k: set(v) for k, v in self.scope_defs[-1].items()}

        self.last_cfg_nodes = [cond_id]
        self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
        
        consequence = node.child_by_field_name("consequence")
        if consequence:
            self.visit(consequence)
            
        true_exits = list(self.last_cfg_nodes)
        true_defs = self.scope_defs.pop()

        self.last_cfg_nodes = [cond_id]
        self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
        
        alternative = node.child_by_field_name("alternative")
        if alternative:
            self.visit(alternative)
            
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

    def visit_call(self, node: Node):
        call_target = self._resolve_call_target(node)
        if call_target and self.current_scope:
            self.collector.add_edge(self.current_scope[-1], call_target, "CALLS", label="INVOKE")
        self.generic_visit(node)
