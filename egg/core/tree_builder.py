import os
from typing import Dict, List, Any
from .gitignore import GitIgnoreMatcher

def generate_tree(repo_path: str) -> List[Dict[str, Any]]:
    repo_path = os.path.abspath(repo_path)
    matcher = GitIgnoreMatcher(repo_path)
    
    # Nested dictionary representing the tree
    # e.g., { "egg": { "core": { "engine.py": None } } }
    tree_dict: Dict[str, Any] = {}
    
    for root, dirs, files in os.walk(repo_path):
        # Prune dirs in place to prevent traversing ignored paths
        dirs[:] = [d for d in dirs if not matcher.should_ignore(os.path.join(root, d))]
        
        for name in dirs + files:
            full_path = os.path.join(root, name)
            if matcher.should_ignore(full_path):
                continue
                
            rel_path = os.path.relpath(full_path, repo_path)
            parts = rel_path.split(os.sep)
            
            curr = tree_dict
            for part in parts[:-1]:
                if part not in curr or curr[part] is None:
                    curr[part] = {}
                curr = curr[part]
            
            leaf_name = parts[-1]
            if os.path.isdir(full_path):
                if leaf_name not in curr or curr[leaf_name] is None:
                    curr[leaf_name] = {}
            else:
                curr[leaf_name] = None

    def dict_to_list(d: Dict[str, Any], parent_path: str = "") -> List[Dict[str, Any]]:
        nodes = []
        if d is None:
            return nodes
            
        for name, content in d.items():
            rel_path = os.path.join(parent_path, name) if parent_path else name
            web_path = rel_path.replace(os.sep, "/")
            
            if content is None:
                nodes.append({
                    "name": name,
                    "path": web_path,
                    "type": "file"
                })
            else:
                children = dict_to_list(content, rel_path)
                children.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
                nodes.append({
                    "name": name,
                    "path": web_path,
                    "type": "directory",
                    "children": children
                })
        
        nodes.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
        return nodes

    return dict_to_list(tree_dict)
