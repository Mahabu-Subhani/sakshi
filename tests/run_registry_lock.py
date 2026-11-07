"""Cross-case memory under concurrent writers.

Eight processes register a different case into the same memory file at the same moment. Every case must be
kept, the file must stay valid JSON, and no lock or temporary file may be left behind. An unreadable memory
file must be left untouched rather than replaced by an empty one.

    python tests/run_registry_lock.py
"""
import json
import multiprocessing as mp
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sakshi.registry import Registry  # noqa: E402

N = 8


def _register(path: str, i: int, start) -> None:
    reg = Registry(path)  # loaded before the others have written: the stale view a real worker has
    start.wait()
    reg.register({"case_id": f"CASE-{i}", "name": f"applicant {i}", "ids": {}, "files": [], "photos": [], "sigs": []})


def main() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "registry.json"
        Registry(path).register({"case_id": "CASE-FIRST", "name": "first", "ids": {}, "files": [], "photos": [], "sigs": []})
        start = mp.get_context("spawn").Event()
        ps = [mp.get_context("spawn").Process(target=_register, args=(str(path), i, start)) for i in range(N)]
        for p in ps:
            p.start()
        start.set()
        for p in ps:
            p.join(60)
        codes = [p.exitcode for p in ps]
        ids = [c["case_id"] for c in json.loads(path.read_text())["cases"]]
        left = sorted(x.name for x in Path(d).iterdir() if x.name != "registry.json")
        checks = [
            ("every writer exited cleanly", codes == [0] * N, codes),
            ("first case kept in first position", ids[:1] == ["CASE-FIRST"], ids[:1]),
            (f"all {N} concurrent cases kept", sorted(ids[1:]) == sorted(f"CASE-{i}" for i in range(N)), len(ids) - 1),
            ("no lock or temporary file left", left == [], left),
        ]
        bad = Path(d) / "broken.json"
        bad.write_text('{"cases": [ {"case_id": "half-writ')
        try:
            Registry(bad).register({"case_id": "X", "name": "x", "ids": {}, "files": [], "photos": [], "sigs": []})
            refused = False
        except RuntimeError:
            refused = True
        checks.append(("unreadable memory left untouched", refused and bad.read_text().endswith("half-writ"), refused))
        for name, passed, detail in checks:
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}  ({detail})")
            ok &= passed
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
