import argparse
import sys
import os

def main():
    parser = argparse.ArgumentParser(description="Egg - Deterministic Codebase Documentation Engine")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    scan_parser = subparsers.add_parser("scan", help="Scan and index a repository path")
    scan_parser.add_argument("target_path", type=str, help="Absolute or relative path to the project directory")
    
    args = parser.parse_args()
    
    if args.command == "scan":
        from egg.core.engine import EggEngine
        target_path = os.path.abspath(args.target_path)
        if not os.path.isdir(target_path):
            print(f"Error: Target path '{target_path}' is not a directory.")
            sys.exit(1)
            
        print(f"[Egg CLI] Initiating incremental scan for repository: {target_path}")
        engine = EggEngine()
        stats = engine.scan_directory(target_path)
        
        print("\n[Egg CLI] Scan Completed Successfully!")
        print(f" - Total files discovered:  {stats['total_files']}")
        print(f" - Files indexed/modified:  {stats['indexed_files']}")
        print(f" - Files skipped/unchanged: {stats['skipped_files']}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
