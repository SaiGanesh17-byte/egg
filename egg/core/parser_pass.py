import ast
from typing import Dict, List, Optional, Set
from .cpg_builder import GraphCollector

class CPGParserPass(ast.NodeVisitor):
    def __init__(self, collector: GraphCollector):
        self.collector = collector
        self.current_scope: List[str] = []
        self.scope_defs: List[Dict[str, Set[str]]] = [{}]
        self.last_cfg_nodes: List[str] = []
        self.class_stack: List[str] = []

    def _extract_target_identifiers(self, node: ast.AST) -> List[str]:
        targets = []
        if isinstance(node, ast.Name):
            targets.append(node.id)
        elif isinstance(node, ast.Attribute):
            name = self._get_qualified_name(node)
            if name:
                targets.append(name)
        elif isinstance(node, ast.Subscript):
            base_name = self._extract_target_identifiers(node.value)
            targets.extend(base_name)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                targets.extend(self._extract_target_identifiers(elt))
        return targets

    def _get_qualified_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parts = []
            curr: ast.AST = node
            while isinstance(curr, ast.Attribute):
                parts.append(curr.attr)
                curr = curr.value
            if isinstance(curr, ast.Name):
                parts.append(curr.id)
            return ".".join(reversed(parts))
        return None

    def _resolve_call_target(self, node: ast.Call) -> Optional[str]:
        raw_target = self._get_qualified_name(node.func)
        if not raw_target:
            return None

        if raw_target.startswith("self.") and self.class_stack:
            method_name = raw_target.split("self.", 1)[1]
            enclosing_class = self.class_stack[-1]
            return f"{self.collector.file_path}::{enclosing_class}.{method_name}"

        return raw_target

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def visit_ClassDef(self, node: ast.ClassDef):
        class_id = f"{self.collector.file_path}::{node.name}"
        if self.current_scope:
            class_id = f"{self.current_scope[-1]}.{node.name}"

        self.collector.add_node(
            node_id=class_id,
            name=node.name,
            kind="CLASS",
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=f"class {node.name}"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], class_id, "AST", label="CONTAINS")

        self.current_scope.append(class_id)
        self.class_stack.append(node.name)

        for stmt in node.body:
            self.visit(stmt)

        self.class_stack.pop()
        self.current_scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        fn_id = f"{self.collector.file_path}::{node.name}"
        if self.current_scope:
            fn_id = f"{self.current_scope[-1]}.{node.name}"

        params = [a.arg for a in node.args.args]
        self.collector.add_node(
            node_id=fn_id,
            name=node.name,
            kind="FUNCTION",
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=f"def {node.name}({', '.join(params)})"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], fn_id, "AST", label="CONTAINS")

        self.current_scope.append(fn_id)
        self.scope_defs.append({param: {fn_id} for param in params})
        
        outer_cfg = self.last_cfg_nodes
        self.last_cfg_nodes = [fn_id]

        for stmt in node.body:
            self.visit(stmt)

        self.scope_defs.pop()
        self.current_scope.pop()
        self.last_cfg_nodes = outer_cfg

    def visit_Assign(self, node: ast.Assign):
        stmt_id = f"{self.collector.file_path}::L{node.lineno}_assign"
        written_vars: List[str] = []
        for target in node.targets:
            written_vars.extend(self._extract_target_identifiers(target))

        self.collector.add_node(
            node_id=stmt_id,
            name=",".join(written_vars) or "assign",
            kind="ASSIGN",
            start_line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            code=ast.unparse(node)
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], stmt_id, "AST", label="CONTAINS")

        self._link_cfg(stmt_id)

        current_defs = self.scope_defs[-1]
        for name_node in ast.walk(node.value):
            if isinstance(name_node, ast.Name) and name_node.id in current_defs:
                for reaching_id in current_defs[name_node.id]:
                    self.collector.add_edge(reaching_id, stmt_id, "DFG", label=name_node.id)

        for var_name in written_vars:
            current_defs[var_name] = {stmt_id}
            self.collector.add_edge(stmt_id, stmt_id, "DFG", label=var_name)

        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        cond_id = f"{self.collector.file_path}::L{node.lineno}_if"
        self.collector.add_node(
            node_id=cond_id,
            name=ast.unparse(node.test),
            kind="BRANCH",
            start_line=node.lineno,
            end_line=node.lineno,
            code=f"if {ast.unparse(node.test)}:"
        )

        if self.current_scope:
            self.collector.add_edge(self.current_scope[-1], cond_id, "AST", label="CONTAINS")

        self._link_cfg(cond_id)
        base_defs = {k: set(v) for k, v in self.scope_defs[-1].items()}

        # True branch
        self.last_cfg_nodes = [cond_id]
        self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
        for stmt in node.body:
            self.visit(stmt)
        true_exits = list(self.last_cfg_nodes)
        true_defs = self.scope_defs.pop()

        # False / Else branch
        self.last_cfg_nodes = [cond_id]
        self.scope_defs.append({k: set(v) for k, v in base_defs.items()})
        for stmt in node.orelse:
            self.visit(stmt)
        false_exits = list(self.last_cfg_nodes)
        false_defs = self.scope_defs.pop()

        # Multi-def merge
        self.last_cfg_nodes = list(set(true_exits + false_exits))
        all_keys = set(base_defs.keys()) | set(true_defs.keys()) | set(false_defs.keys())
        merged: Dict[str, Set[str]] = {}

        for k in all_keys:
            t_set = true_defs.get(k, base_defs.get(k, set()))
            f_set = false_defs.get(k, base_defs.get(k, set()))
            merged[k] = t_set | f_set

        self.scope_defs[-1] = merged

    def visit_Call(self, node: ast.Call):
        call_target = self._resolve_call_target(node)
        if call_target and self.current_scope:
            self.collector.add_edge(self.current_scope[-1], call_target, "CALLS", label="INVOKE")
        self.generic_visit(node)
