import os
import fnmatch
import re

class GitIgnoreMatcher:
    def __init__(self, root_dir: str):
        self.root_dir = os.path.abspath(root_dir)
        self.patterns = []
        self._load_gitignore()

    def _load_gitignore(self):
        # Default global ignore directories/files
        self.default_ignores = {
            ".git",
            ".egg",
            "node_modules",
            "venv",
            ".venv",
            "__pycache__",
            ".next",
            "dist",
            "build",
            ".DS_Store"
        }
        
        gitignore_path = os.path.join(self.root_dir, ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    negate = False
                    if line.startswith("!"):
                        negate = True
                        line = line[1:]
                    
                    self.patterns.append((line, not negate))

    def should_ignore(self, path: str) -> bool:
        # Resolve absolute and relative paths
        abs_path = os.path.abspath(path)
        rel_path = os.path.relpath(abs_path, self.root_dir)
        
        if rel_path == "." or rel_path == "..":
            return False
            
        parts = rel_path.split(os.sep)
        
        # 1. Hardcoded check for system-wide directories
        for part in parts:
            if part in self.default_ignores:
                return True
                
        # Normalize relative path using forward slashes for matching patterns
        norm_rel = rel_path.replace(os.sep, "/")
        
        # 2. Match patterns loaded from .gitignore
        ignored = False
        for pattern, is_ignore in self.patterns:
            # Trailing slash indicates directory-only match
            dir_only = pattern.endswith("/")
            pat = pattern.rstrip("/")
            
            # If there are no slashes inside the pattern, match against any path segment name
            if "/" not in pat:
                match_found = False
                for part in parts:
                    if fnmatch.fnmatch(part, pat):
                        match_found = True
                        break
                if match_found:
                    ignored = is_ignore
            else:
                # Match relative to root
                # If pat starts with a slash, strip it for matching relative to root
                if pat.startswith("/"):
                    pat = pat[1:]
                
                # Check fnmatch against relative path
                if fnmatch.fnmatch(norm_rel, pat) or fnmatch.fnmatch(norm_rel, pat + "/*") or norm_rel.startswith(pat + "/"):
                    ignored = is_ignore
                    
        return ignored
