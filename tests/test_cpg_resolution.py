import os
import shutil
import tempfile
import sqlite3
from pathlib import Path
from egg.core.engine import EggEngine
from egg.server.app import get_cpg_slice, get_db_path_for_repo

def test_java_resolution_scenarios(temp_repo, db_path):
    print("  Running Java resolution scenarios...")
    os.makedirs(os.path.join(temp_repo, "media"), exist_ok=True)
    os.makedirs(os.path.join(temp_repo, "media", "external"), exist_ok=True)
    
    video_object_content = """
    package media;
    public interface VideoObject {
        void accept(String visitor);
    }
    """
    
    real_video_content = """
    package media;
    public class RealVideoObject implements VideoObject {
        public void accept(String visitor) {}
    }
    """
    
    dead_interface_content = """
    package media;
    public interface DeadInterface {
        void process();
    }
    """

    dead_impl_content = """
    package media;
    public class DeadImpl implements DeadInterface {
        public void process() {}
    }
    """

    two_sub_interface_content = """
    package media;
    public interface TwoSubInterface {
        void execute();
    }
    """

    sub_one_content = """
    package media;
    public class SubOne implements TwoSubInterface {
        public void execute() {}
    }
    """

    sub_two_content = """
    package media;
    public class SubTwo implements TwoSubInterface {
        public void execute() {}
    }
    """

    tentative_interface_content = """
    package media.external;
    public interface TentativeInterface {
        void resolve();
    }
    """

    tentative_impl_content = """
    package media;
    public class TentativeImpl implements TentativeInterface {
        public void resolve() {}
    }
    """

    main_content = """
    package media;
    public class Main {
        public void run() {
            VideoObject video = new RealVideoObject();
            video.accept("test");

            TwoSubInterface one = new SubOne();
            one.execute();
            TwoSubInterface two = new SubTwo();
            two.execute();

            TentativeImpl tent = new TentativeImpl();
        }
    }
    """
    
    with open(os.path.join(temp_repo, "media", "VideoObject.java"), "w") as f:
        f.write(video_object_content)
    with open(os.path.join(temp_repo, "media", "RealVideoObject.java"), "w") as f:
        f.write(real_video_content)
    with open(os.path.join(temp_repo, "media", "DeadInterface.java"), "w") as f:
        f.write(dead_interface_content)
    with open(os.path.join(temp_repo, "media", "DeadImpl.java"), "w") as f:
        f.write(dead_impl_content)
    with open(os.path.join(temp_repo, "media", "TwoSubInterface.java"), "w") as f:
        f.write(two_sub_interface_content)
    with open(os.path.join(temp_repo, "media", "SubOne.java"), "w") as f:
        f.write(sub_one_content)
    with open(os.path.join(temp_repo, "media", "SubTwo.java"), "w") as f:
        f.write(sub_two_content)
    with open(os.path.join(temp_repo, "media", "external", "TentativeInterface.java"), "w") as f:
        f.write(tentative_interface_content)
    with open(os.path.join(temp_repo, "media", "TentativeImpl.java"), "w") as f:
        f.write(tentative_impl_content)
    with open(os.path.join(temp_repo, "media", "Main.java"), "w") as f:
        f.write(main_content)

    engine = EggEngine(db_path)
    engine.scan_directory(temp_repo)

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        
        # Test Case 1: Static Assumed
        res1 = engine.resolve_call_site("media.RealVideoObject", "accept", cur)
        assert res1["resolution"] == "static-assumed", f"Expected static-assumed, got {res1['resolution']}"
        assert "media.RealVideoObject" in res1["classes"]

        # Test Case 2: RTA Split (Instantiated match vs Dead Code)
        res2 = engine.resolve_call_site("media.VideoObject", "accept", cur)
        assert res2["resolution"] == "rta-resolved", f"Expected rta-resolved, got {res2['resolution']}"
        assert "media.RealVideoObject" in res2["classes"]

        # Test Case 3: cha-dead-or-external
        res3 = engine.resolve_call_site("media.DeadInterface", "process", cur)
        assert res3["resolution"] == "cha-dead-or-external", f"Expected cha-dead-or-external, got {res3['resolution']}"

        # Test Case 4: rta-narrowed
        res4 = engine.resolve_call_site("media.TwoSubInterface", "execute", cur)
        assert res4["resolution"] == "rta-narrowed", f"Expected rta-narrowed, got {res4['resolution']}"
        assert "media.SubOne" in res4["classes"] and "media.SubTwo" in res4["classes"]

        # Test Case 5: rta-resolved-tentative
        res5 = engine.resolve_call_site("media.external.TentativeInterface", "resolve", cur)
        assert res5["resolution"] == "rta-resolved-tentative", f"Expected rta-resolved-tentative, got {res5['resolution']}"
        assert "media.TentativeImpl" in res5["classes"]

        # Test Case 6: Aggregate DB Stats Confidence Summary
        from egg.server.app import get_db_stats
        db_storage_dir = os.path.dirname(db_path)
        app_expected_db = get_db_path_for_repo(temp_repo, db_storage_dir)
        os.makedirs(os.path.dirname(app_expected_db), exist_ok=True)
        shutil.copy(db_path, app_expected_db)
        
        stats = get_db_stats(repo_path=temp_repo, db_storage_path=db_storage_dir)
        conf = stats["confidence_summary"]
        assert conf["high"] > 0, f"Expected at least one high confidence resolved call, got: {conf}"
        assert conf["medium"] > 0, f"Expected at least one medium confidence resolved call, got: {conf}"

    print("  Java resolution scenarios passed!")

def test_go_structural_interface_matching(temp_repo, db_path):
    print("  Running Go structural interface matching...")
    os.makedirs(os.path.join(temp_repo, "db"), exist_ok=True)
    
    content = """
    package db
    
    type Reader interface {
        Read(p []byte) (n int, err error)
    }
    
    type Buffer struct {
        data []byte
    }
    
    func (b *Buffer) Read(p []byte) (n int, err error) {
        return 0, nil
    }
    """
    with open(os.path.join(temp_repo, "db", "db.go"), "w") as f:
        f.write(content)

    engine = EggEngine(db_path)
    engine.scan_directory(temp_repo)

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        
        cur.execute("SELECT child_id, parent_id FROM class_hierarchy WHERE relation_type = 'IMPLEMENTS'")
        rows = cur.fetchall()
        assert len(rows) > 0, "Expected implements relation in class_hierarchy"
        assert ("db.Buffer", "db.Reader") in rows, f"Expected Buffer implements Reader, got {rows}"
    print("  Go structural interface matching passed!")

def test_rust_trait_qualification_scenarios(temp_repo, db_path):
    print("  Running Rust trait qualification...")
    os.makedirs(os.path.join(temp_repo, "src"), exist_ok=True)
    
    content = """
    pub trait Handler {
        fn handle(&self);
    }
    
    pub struct ApiHandler;
    
    impl Handler for ApiHandler {
        fn handle(&self) {}
    }
    """
    with open(os.path.join(temp_repo, "src", "lib.rs"), "w") as f:
        f.write(content)

    engine = EggEngine(db_path)
    engine.scan_directory(temp_repo)

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        
        cur.execute("SELECT child_id, parent_id FROM class_hierarchy WHERE relation_type = 'IMPLEMENTS'")
        rows = cur.fetchall()
        assert len(rows) > 0, "Expected implements relation in class_hierarchy"
        assert ("crate::ApiHandler", "crate::Handler") in rows, f"Expected ApiHandler implements Handler, got {rows}"
    print("  Rust trait qualification passed!")

def test_cpg_slice_dfg_flow_types(temp_repo, db_path):
    print("  Running CPG Slice DFG Flow Type scenarios...")
    
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
    
    os.makedirs(os.path.join(temp_repo, "media"), exist_ok=True)
    with open(os.path.join(temp_repo, "media", "FlowTest.java"), "w") as f:
        f.write(mixed_content)
    with open(os.path.join(temp_repo, "media", "FlowTest2.java"), "w") as f:
        f.write(same_branch_content)
    with open(os.path.join(temp_repo, "media", "FlowTest3.java"), "w") as f:
        f.write(lambda_content)
    with open(os.path.join(temp_repo, "media", "FlowTest4.java"), "w") as f:
        f.write(sibling_ifs_content)

    # Scan & compile
    engine = EggEngine(db_path)
    engine.scan_directory(temp_repo)

    # Sync expected DB file path for FastAPI routing
    db_storage_dir = os.path.dirname(db_path)
    app_expected_db = get_db_path_for_repo(temp_repo, db_storage_dir)
    os.makedirs(os.path.dirname(app_expected_db), exist_ok=True)
    shutil.copy(db_path, app_expected_db)

    # TEST CASE 1: Mixed flow verification
    symbol_mixed = "media/FlowTest.java::FlowTest.testMixed(int)"
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id=symbol_mixed)
    df_list = data["data_flow"]
    
    x_flow = next((df for df in df_list if df["symbol"] == "x" and df["operation"] == "parameter"), None)
    assert x_flow is not None, f"Expected x parameter flow, got: {df_list}"
    
    flows_to = x_flow["flows_to"]
    assert len(flows_to) == 2, f"Expected 2 groups, got: {flows_to}"
    
    cond_group = next((f for f in flows_to if f["flow_type"] == "conditional_branch"), None)
    assert cond_group is not None
    assert set(cond_group["targets"]) == {"z", "w"}
    
    seq_group = next((f for f in flows_to if f["flow_type"] == "sequential"), None)
    assert seq_group is not None
    assert set(seq_group["targets"]) == {"y"}

    # TEST CASE 2: Sibling same-branch flow
    symbol_same = "media/FlowTest2.java::FlowTest2.testSameBranch(int)"
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id=symbol_same)
    df_list = data["data_flow"]
    x_flow = next((df for df in df_list if df["symbol"] == "x" and df["operation"] == "parameter"), None)
    assert x_flow is not None
    flows_to = x_flow["flows_to"]
    assert len(flows_to) == 1
    assert flows_to[0]["flow_type"] == "fan_out"
    assert set(flows_to[0]["targets"]) == {"z", "w"}

    # TEST CASE 3: Lambda scope cutoff
    symbol_lambda = "media/FlowTest3.java::FlowTest3.testLambda(int)"
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id=symbol_lambda)
    df_list = data["data_flow"]
    assert not any(df["symbol"] == "nestedVar" for df in df_list), f"nestedVar leaked to outer scope: {df_list}"

    # TEST CASE 4: Sibling independent conditionals (clique separation)
    symbol_siblings = "media/FlowTest4.java::FlowTest4.testSiblingIfs(int)"
    data = get_cpg_slice(repo_path=temp_repo, db_storage_path=db_storage_dir, symbol_id=symbol_siblings)
    df_list = data["data_flow"]
    x_flow = next((df for df in df_list if df["symbol"] == "x" and df["operation"] == "parameter"), None)
    assert x_flow is not None
    flows_to = x_flow["flows_to"]
    
    assert len(flows_to) == 2, f"Expected 2 groups, got: {flows_to}"
    assert all(f["flow_type"] == "conditional_branch" for f in flows_to)
    targets_sets = [set(f["targets"]) for f in flows_to]
    assert {"a", "b"} in targets_sets
    assert {"c", "d"} in targets_sets

    print("  CPG Slice DFG Flow Type scenarios passed!")

def main():
    print("Starting Multi-Language Call Graph Slicing verification suite...")
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "graph.db")
    try:
        test_java_resolution_scenarios(temp_dir, db_file)
        test_go_structural_interface_matching(temp_dir, db_file)
        test_rust_trait_qualification_scenarios(temp_dir, db_file)
        test_cpg_slice_dfg_flow_types(temp_dir, db_file)
        print("ALL TESTS PASSED SUCCESSFULLY!")
    finally:
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    main()
