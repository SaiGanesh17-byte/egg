from abc import ABC, abstractmethod
from tree_sitter import Node
from egg.core.cpg_builder import GraphCollector

class BaseParser(ABC):
    def __init__(self, file_path: str, source_code: str, collector: GraphCollector):
        self.file_path = file_path
        self.source_code = source_code
        self.collector = collector
        self.source_bytes = source_code.encode("utf-8")

    @abstractmethod
    def parse(self, root_node: Node):
        pass

    def _get_text(self, node: Node) -> str:
        if node is None:
            return ""
        return self.source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def visit(self, node: Node):
        if node is None:
            return
        node_type = node.type
        clean_type = node_type.replace("-", "_").replace(".", "_")
        method_name = f"visit_{clean_type}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: Node):
        for child in node.children:
            self.visit(child)
