import os
import shutil
import tempfile
import sqlite3
from pathlib import Path
from egg.core.engine import EggEngine

def verify():
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "graph.db")
    try:
        # -------------------------------------------------------------
        # Create Java, Go, Rust fixtures
        # -------------------------------------------------------------
        os.makedirs(os.path.join(temp_dir, "media"), exist_ok=True)
        os.makedirs(os.path.join(temp_dir, "media", "external"), exist_ok=True)
        os.makedirs(os.path.join(temp_dir, "db"), exist_ok=True)
        os.makedirs(os.path.join(temp_dir, "src"), exist_ok=True)

        # Java: VideoObject and RealVideoObject
        with open(os.path.join(temp_dir, "media", "VideoObject.java"), "w") as f:
            f.write("""
            package media;
            public interface VideoObject {
                void accept(String visitor);
            }
            """)
        with open(os.path.join(temp_dir, "media", "RealVideoObject.java"), "w") as f:
            f.write("""
            package media;
            public class RealVideoObject implements VideoObject {
                public void accept(String visitor) {}
            }
            """)

        # Java Dead / External code: DeadInterface and DeadImpl (never instantiated)
        with open(os.path.join(temp_dir, "media", "DeadInterface.java"), "w") as f:
            f.write("""
            package media;
            public interface DeadInterface {
                void process();
            }
            """)
        with open(os.path.join(temp_dir, "media", "DeadImpl.java"), "w") as f:
            f.write("""
            package media;
            public class DeadImpl implements DeadInterface {
                public void process() {}
            }
            """)

        # Java RTA-Narrowed: TwoSubInterface with two instantiated implementations
        with open(os.path.join(temp_dir, "media", "TwoSubInterface.java"), "w") as f:
            f.write("""
            package media;
            public interface TwoSubInterface {
                void execute();
            }
            """)
        with open(os.path.join(temp_dir, "media", "SubOne.java"), "w") as f:
            f.write("""
            package media;
            public class SubOne implements TwoSubInterface {
                public void execute() {}
            }
            """)
        with open(os.path.join(temp_dir, "media", "SubTwo.java"), "w") as f:
            f.write("""
            package media;
            public class SubTwo implements TwoSubInterface {
                public void execute() {}
            }
            """)

        # Java RTA-Resolved-Tentative: TentativeInterface in media.external, 
        # and TentativeImpl in media. TentativeImpl does NOT import TentativeInterface explicitly,
        # forcing the parser to resolve it via simple-name fallback matching (unqualified = 1).
        with open(os.path.join(temp_dir, "media", "external", "TentativeInterface.java"), "w") as f:
            f.write("""
            package media.external;
            public interface TentativeInterface {
                void resolve();
            }
            """)
        with open(os.path.join(temp_dir, "media", "TentativeImpl.java"), "w") as f:
            f.write("""
            package media;
            public class TentativeImpl implements TentativeInterface {
                public void resolve() {}
            }
            """)

        # Main: Instantiates RealVideoObject, SubOne, SubTwo, and TentativeImpl
        with open(os.path.join(temp_dir, "media", "Main.java"), "w") as f:
            f.write("""
            package media;
            public class Main {
                public void run() {
                    VideoObject video = new RealVideoObject();
                    video.accept("test");
                    
                    TwoSubInterface one = new SubOne();
                    TwoSubInterface two = new SubTwo();
                    
                    TentativeImpl tent = new TentativeImpl();
                }
            }
            """)

        # Go: Reader interface, Buffer struct
        with open(os.path.join(temp_dir, "db", "db.go"), "w") as f:
            f.write("""
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
            """)

        # Rust: Handler trait, ApiHandler struct impl
        with open(os.path.join(temp_dir, "src", "lib.rs"), "w") as f:
            f.write("""
            pub trait Handler {
                fn handle(&self);
            }
            pub struct ApiHandler;
            impl Handler for ApiHandler {
                fn handle(&self) {}
            }
            """)

        # -------------------------------------------------------------
        # Index repo using EggEngine
        # -------------------------------------------------------------
        engine = EggEngine(db_file)
        engine.scan_directory(temp_dir)

        # -------------------------------------------------------------
        # Connect to DB and print tables
        # -------------------------------------------------------------
        with sqlite3.connect(db_file) as conn:
            cur = conn.cursor()
            
            print("==================================================================")
            print("1. DISCOVERED DECLARATIONS (Discovered in Pass 1 namespace sweep)")
            print("==================================================================")
            cur.execute("SELECT qualified_name, decl_kind, file_path FROM discovered_declarations ORDER BY qualified_name")
            for r in cur.fetchall():
                print(f"  QName: {r[0]:<35} | Kind: {r[1]:<10} | File: {r[2]}")
                
            print("\n==================================================================")
            print("2. CLASS HIERARCHY (Inheritance mappings - EXTENDS/IMPLEMENTS)")
            print("==================================================================")
            cur.execute("SELECT child_id, parent_id, relation_type, unqualified FROM class_hierarchy ORDER BY relation_type, child_id")
            for r in cur.fetchall():
                print(f"  Child: {r[0]:<35} | Parent: {r[1]:<30} | Rel: {r[2]:<10} | Unqualified: {r[3]}")

            print("\n==================================================================")
            print("3. INSTANTIATIONS (Object creations / annotations)")
            print("==================================================================")
            cur.execute("SELECT class_id, instantiation_type, file_path, line_number FROM instantiations ORDER BY class_id")
            for r in cur.fetchall():
                print(f"  Class: {r[0]:<35} | Type: {r[1]:<15} | File: {r[2]} (L{r[3]})")

            print("\n==================================================================")
            print("4. CONCRETE call_site RESOLUTIONS (resolve_call_site output)")
            print("==================================================================")
            
            # Scenario A: rta-resolved (1 surviving subclass, path is fully qualified)
            res_rta = engine.resolve_call_site("media.VideoObject", "accept", cur)
            print(f"  Virtual call VideoObject.accept():\n    -> {res_rta}")
            
            # Scenario B: static-assumed (No subclasses)
            res_static = engine.resolve_call_site("media.RealVideoObject", "accept", cur)
            print(f"  Virtual call RealVideoObject.accept():\n    -> {res_static}")

            # Scenario C: cha-dead-or-external (RTA ran globally, but none of these specific candidates are instantiated)
            res_dead = engine.resolve_call_site("media.DeadInterface", "process", cur)
            print(f"  Virtual call DeadInterface.process():\n    -> {res_dead}")

            # Scenario D: rta-narrowed (2+ active candidates remain instantiated)
            res_narrowed = engine.resolve_call_site("media.TwoSubInterface", "execute", cur)
            print(f"  Virtual call TwoSubInterface.execute():\n    -> {res_narrowed}")

            # Scenario E: rta-resolved-tentative (1 candidate instantiated, but resolution path had unqualified guess)
            res_tentative = engine.resolve_call_site("media.external.TentativeInterface", "resolve", cur)
            print(f"  Virtual call TentativeInterface.resolve():\n    -> {res_tentative}")

            print("==================================================================")

    finally:
        shutil.rmtree(temp_dir)

if __name__ == "__main__":
    verify()
