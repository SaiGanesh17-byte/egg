from tree_sitter import Node
from typing import List, Optional
from .base_parser import BaseParser

class SQLParser(BaseParser):
    def __init__(self, file_path: str, source_code: str, collector):
        super().__init__(file_path, source_code, collector)
        self.current_scope: List[str] = []
        self.last_cfg_nodes: List[str] = []

    def parse(self, root_node: Node):
        self.visit(root_node)

    def _extract_table_name(self, node: Node) -> str:
        if node.type in ("relation_name", "object_reference", "identifier", "keyword"):
            if node.type == "keyword":
                return ""
            return self._get_text(node).strip('"`[]')
            
        for child in node.children:
            name = self._extract_table_name(child)
            if name:
                return name
        return ""

    def _link_cfg(self, target_id: str, label: str = "NEXT"):
        for prev_id in self.last_cfg_nodes:
            self.collector.add_edge(prev_id, target_id, "CFG", label=label)
        self.last_cfg_nodes = [target_id]

    def visit_create_table(self, node: Node):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        table_name = ""
        for child in node.children:
            if child.type in ("relation_name", "object_reference", "keyword"):
                if child.type != "keyword":
                    table_name = self._get_text(child).strip('"`[]')
                    break
        
        if not table_name:
            table_name = self._extract_table_name(node) or f"table_L{start_line}"
            
        table_id = f"SQL::TABLE.{table_name}"
        
        self.collector.add_node(
            node_id=table_id,
            name=table_name,
            kind="TABLE",
            start_line=start_line,
            end_line=end_line,
            signature=f"CREATE TABLE {table_name}",
            code=self._get_text(node)
        )
        
        self._link_cfg(table_id)
        self.generic_visit(node)

    def visit_insert(self, node: Node):
        self._handle_mutation(node, "INSERT")

    def visit_update(self, node: Node):
        self._handle_mutation(node, "UPDATE")

    def visit_delete(self, node: Node):
        self._handle_mutation(node, "DELETE")

    def _handle_mutation(self, node: Node, mut_type: str):
        start_line = node.start_point[0] + 1
        end_line = node.end_point[0] + 1
        
        table_name = ""
        for child in node.children:
            if child.type in ("relation_name", "object_reference"):
                table_name = self._get_text(child).strip('"`[]')
                break
                
        if not table_name:
            table_name = self._extract_table_name(node) or "unknown"
            
        stmt_id = f"{self.file_path}::L{start_line}_{mut_type.lower()}"
        
        self.collector.add_node(
            node_id=stmt_id,
            name=f"{mut_type} {table_name}",
            kind="ASSIGN",
            start_line=start_line,
            end_line=end_line,
            code=self._get_text(node)
        )
        
        self._link_cfg(stmt_id)
        
        table_id = f"SQL::TABLE.{table_name}"
        self.collector.add_edge(stmt_id, table_id, "DFG", label=f"mutates {table_name}")
        
        self.generic_visit(node)
