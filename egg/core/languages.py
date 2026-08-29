from typing import Optional
from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_typescript
import tree_sitter_sql
import tree_sitter_rust
import tree_sitter_go
import tree_sitter_java

# Pre-load grammars
LANG_PYTHON = Language(tree_sitter_python.language())
LANG_TYPESCRIPT = Language(tree_sitter_typescript.language_typescript())
LANG_TSX = Language(tree_sitter_typescript.language_tsx())
LANG_SQL = Language(tree_sitter_sql.language())
LANG_RUST = Language(tree_sitter_rust.language())
LANG_GO = Language(tree_sitter_go.language())
LANG_JAVA = Language(tree_sitter_java.language())

def get_language_for_extension(ext: str) -> Optional[Language]:
    ext = ext.lower().lstrip(".")
    if ext == "py":
        return LANG_PYTHON
    elif ext in ("ts", "js"):
        return LANG_TYPESCRIPT
    elif ext in ("tsx", "jsx"):
        return LANG_TSX
    elif ext == "sql":
        return LANG_SQL
    elif ext == "rs":
        return LANG_RUST
    elif ext == "go":
        return LANG_GO
    elif ext == "java":
        return LANG_JAVA
    return None

def get_parser_for_extension(ext: str) -> Optional[Parser]:
    lang = get_language_for_extension(ext)
    if lang:
        return Parser(lang)
    return None
