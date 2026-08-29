import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class CPGNode:
    id: str
    name: str
    kind: str                         # 'CLASS', 'FUNCTION', 'ASSIGN', 'BRANCH', 'CALL'
    file_path: str
    start_line: int
    end_line: int
    signature: Optional[str] = None
    code: str = ""

@dataclass
class CPGEdge:
    source: str
    target: str
    edge_type: str                    # 'AST', 'CFG', 'DFG', 'CALLS'
    label: str = ""

class GraphCollector:
    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.source_code = source_code
        self.nodes: Dict[str, CPGNode] = {}
        self.edges: List[CPGEdge] = []
        self.file_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    def add_node(self, node_id: str, name: str, kind: str, start_line: int, end_line: int, **kwargs) -> str:
        self.nodes[node_id] = CPGNode(
            id=node_id,
            name=name,
            kind=kind,
            file_path=self.file_path,
            start_line=start_line,
            end_line=end_line,
            signature=kwargs.get("signature"),
            code=kwargs.get("code", "")
        )
        return node_id

    def add_edge(self, source: str, target: str, edge_type: str, label: str = ""):
        self.edges.append(CPGEdge(source=source, target=target, edge_type=edge_type, label=label))
