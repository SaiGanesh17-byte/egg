import os
import glob
from egg.core.engine import EggEngine

def main():
    engine = EggEngine(db_path=".egg/graph.db")
    
    # Example: Scan and parse all python files in the current directory
    py_files = glob.glob("**/*.py", recursive=True)
    indexed_count = 0

    print(f"[Egg] Scanning {len(py_files)} files...")
    for file_path in py_files:
        if file_path.startswith(".egg") or "venv" in file_path:
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
            if engine.process_file(file_path, code):
                indexed_count += 1

    print(f"[Egg] Done! Indexed {indexed_count} changed/new files into .egg/graph.db")

if __name__ == "__main__":
    main()
