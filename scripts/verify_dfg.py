import os
import shutil
import tempfile
import json
import sqlite3
from egg.core.engine import EggEngine
from egg.server.app import get_cpg_slice, get_db_path_for_repo

def run_verification():
    temp_repo = tempfile.mkdtemp()
    db_storage_dir = tempfile.mkdtemp()
    db_path = os.path.join(db_storage_dir, "graph.db")
    
    # 1. Mixed flow (unconditional + conditional)
    mixed_content = """
    package media;
    public class FlowTest {
        public void testMixed(int x) {
            int y = x;
            if (x > 0) {
                int z = x;
            } else {
                int w = x;
            }
        }
    }
    """
    
    # 2. Sibling same-branch flow (non-exclusive inside same consequence arm)
    same_branch_content = """
    package media;
    public class FlowTest2 {
        public void testSameBranch(int x) {
            if (x > 0) {
                int z = x;
                int w = x;
            }
        }
    }
    """
    
    # 3. AST contained walk with nested closure
    lambda_content = """
    package media;
    import java.util.function.Consumer;
    public class FlowTest3 {
        public void testLambda(int x) {
            int y = x;
            Consumer<Integer> runner = (val) -> {
                int nestedVar = val;
            };
        }
    }
    """
    
    # 4. Sibling independent conditionals (clique separation)
    sibling_ifs_content = """
    package media;
    public class FlowTest4 {
        public void testSiblingIfs(int x) {
            int a = 0;
            int b = 0;
            int c = 0;
            int d = 0;
            if (x > 0) {
                a = x;
            } else {
                b = x;
            }
            if (x > 10) {
                c = x;
            } else {
                d = x;
            }
        }
    }
    """

    # 5. Nested conditionals
    nested_content = """
    package media;
    public class FlowTest5 {
        public void testNested(int x) {
            if (x > 0) {
                if (x > 10) {
                    int z = x;
                } else {
                    int w = x;
                }
            }
        }
    }
    """

    os.makedirs(os.path.join(temp_repo, "media"), exist_ok=True)
    with open(os.path.join(temp_repo, "media", "FlowTest.java"), "w") as f:
        f.write(mixed_content)
    with open(os.path.join(temp_repo, "media", "FlowTest2.java"), "w") as f:
        f.write(same_branch_content)
    with open(os.path.join(temp_repo, "media", "FlowTest3.java"), "w") as f:
        f.write(lambda_content)
    with open(os.path.join(temp_repo, "media", "FlowTest4.java"), "w") as f:
        f.write(sibling_ifs_content)
    with open(os.path.join(temp_repo, "media", "FlowTest5.java"), "w") as f:
        f.write(nested_content)

    # Scan & compile
    engine = EggEngine(db_path)
    engine.scan_directory(temp_repo)

    # Sync expected DB file path for FastAPI routing
    app_expected_db = get_db_path_for_repo(temp_repo, db_storage_dir)
    os.makedirs(os.path.dirname(app_expected_db), exist_ok=True)
    shutil.copy(db_path, app_expected_db)

    print("==================================================================")
    print("1. MIXED FLOW CASE (x -> y [unconditional], z/w [conditional])")
    print("==================================================================")
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id="media/FlowTest.java::FlowTest.testMixed(int)")
    print(json.dumps(data["data_flow"], indent=2))

    print("\n==================================================================")
    print("2. SAME-BRANCH FLOW CASE (z and w in same consequence arm)")
    print("==================================================================")
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id="media/FlowTest2.java::FlowTest2.testSameBranch(int)")
    print(json.dumps(data["data_flow"], indent=2))

    print("\n==================================================================")
    print("3. LAMBDA CUTOFF CASE (nestedVar inside lambda block)")
    print("==================================================================")
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id="media/FlowTest3.java::FlowTest3.testLambda(int)")
    print(json.dumps(data["data_flow"], indent=2))

    print("\n==================================================================")
    print("4. INDEPENDENT SIBLING CONDITIONALS (clique separation: [a,b] vs [c,d])")
    print("==================================================================")
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id="media/FlowTest4.java::FlowTest4.testSiblingIfs(int)")
    print(json.dumps(data["data_flow"], indent=2))

    print("\n==================================================================")
    print("5. NESTED CONDITIONALS (z and w in nested inner branches)")
    print("==================================================================")
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id="media/FlowTest5.java::FlowTest5.testNested(int)")
    print(json.dumps(data["data_flow"], indent=2))

    shutil.rmtree(temp_repo)
    shutil.rmtree(db_storage_dir)

if __name__ == "__main__":
    run_verification()
