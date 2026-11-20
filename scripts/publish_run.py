#!/usr/bin/env python3
"""Publish a finished benchmark run, or check everything already published.

Publish (after `python3 export.py --run <run> --public` and `score.py` in the suite folder):

    python3 scripts/publish_run.py --suite s1-event-recall --run 2026-11-24

  1. verifies the exported tables are the public cut (no Exa rows, no snippets);
  2. creates benchmarks/<suite>/results/<run>/ with the small tables, scores.md, a queries.json snapshot,
     README.md (from templates/run-readme.md) and MANIFEST.json;
  3. builds dist/<suite>_<run>_public-data.zip with the row-level tables, for the GitHub Release;
  4. prints the commands for the remaining manual steps.

Check (also run by CI on every pull request):

    python3 scripts/publish_run.py --check

Standard library only (Python 3.11+).
"""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
DIST = ROOT / "dist"

FORBIDDEN_COLUMNS = {"snippet_returned", "judge_input_snippet"}  # publishers' text: never published
EXA_PREFIX = "exa_"  # Exa's terms restrict redistributing its output
EXA_ALLOWED_IN = ("_summary_by_system.csv", "systems.csv")  # aggregate-only files, as export.py --public writes them
COMMITTED_SUFFIXES = ("_queries.csv", "_summary_by_system.csv", "_metrics_per_query_window.csv", "systems.csv")
MAX_COMMITTED_BYTES = 5 * 1024 * 1024  # anything bigger belongs in the Release zip
FORBIDDEN_NAMES = {".env", ".key", "raw", "judge", "benchmarks.sqlite", "pools.jsonl", "map.json"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_csv_text(name: str, text: str) -> list[str]:
    """Problems in one CSV: snippet columns, or Exa rows outside the aggregate-only files."""
    problems = []
    reader = csv.reader(io.StringIO(text))
    header = next(reader, [])
    bad = FORBIDDEN_COLUMNS.intersection(header)
    if bad:
        problems.append(f"{name}: snippet columns present: {sorted(bad)}")
    if not name.endswith(EXA_ALLOWED_IN):
        for n, row in enumerate(reader, start=2):
            if any(cell.startswith(EXA_PREFIX) for cell in row):
                problems.append(f"{name}: Exa row at line {n} (only aggregate-only files may name Exa)")
                break
    return problems


def check_files(files: list[Path], label: str) -> list[str]:
    """Check CSVs, and CSVs inside zips, for the public-cut rules."""
    problems = []
    for f in files:
        if f.name in FORBIDDEN_NAMES or f.suffix == ".sqlite":
            problems.append(f"{label}/{f.name}: must never be published")
        elif f.suffix == ".csv":
            problems += check_csv_text(f"{label}/{f.name}", f.read_text(encoding="utf-8"))
        elif f.suffix == ".zip":
            with zipfile.ZipFile(f) as z:
                for member in z.namelist():
                    base = Path(member).name
                    if base.endswith(".csv"):
                        problems += check_csv_text(f"{label}/{f.name}:{member}", z.read(member).decode("utf-8"))
                    elif base in FORBIDDEN_NAMES or base.endswith(".sqlite"):
                        problems.append(f"{label}/{f.name}:{member}: must never be published")
    return problems


def check_published() -> int:
    """Check every folder under benchmarks/*/results/."""
    problems, n = [], 0
    for res in sorted(BENCH.glob("*/results/*/")):
        if not res.is_dir():
            continue
        n += 1
        label = str(res.relative_to(ROOT))
        files = [p for p in res.rglob("*") if p.is_file()]
        for p in files:
            if p.stat().st_size > MAX_COMMITTED_BYTES:
                problems.append(f"{label}/{p.name}: over {MAX_COMMITTED_BYTES // 2**20} MB, ship it in the Release zip")
            if p.name == "README.md" and "TODO" in p.read_text(encoding="utf-8"):
                problems.append(f"{label}/README.md: unresolved TODO")
        problems += check_files(files, label)
        manifest = res / "MANIFEST.json"
        if not manifest.exists():
            problems.append(f"{label}: MANIFEST.json missing")
            continue
        m = json.loads(manifest.read_text(encoding="utf-8"))
        for entry in m.get("files", []):
            p = res / entry["name"]
            if not p.exists():
                problems.append(f"{label}: manifest lists {entry['name']}, which is missing")
            elif sha256_file(p) != entry["sha256"]:
                problems.append(f"{label}: {entry['name']} changed since publication (folders are immutable)")
    for p in problems:
        print("FAIL", p)
    print(f"checked {n} published run folder(s): {'FAILED' if problems else 'ok'}")
    return 1 if problems else 0


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def publish(suite: str, run: str) -> int:
    sdir = BENCH / suite
    prefix = suite.split("-")[0]  # s1, s2 ...
    data = sdir / "data" / run
    scores = sdir / "runs" / run / "scores.md"
    dest = sdir / "results" / run
    if not sdir.is_dir():
        sys.exit(f"no such suite: {sdir}")
    if not data.is_dir():
        sys.exit(f"{data} missing. From {sdir.relative_to(ROOT)} run: python3 export.py --run {run} --public")
    if not scores.is_file():
        sys.exit(f"{scores} missing. Run: python3 score.py --run {run} > runs/{run}/scores.md")
    if dest.exists():
        sys.exit(f"{dest.relative_to(ROOT)} already exists. Published runs are immutable: add an Errata section "
                 f"to its README instead, or publish a new run.")

    tables = sorted(p for p in data.iterdir() if p.is_file() and p.suffix == ".csv")
    if not tables:
        sys.exit(f"no CSV tables in {data}")
    problems = check_files(tables, str(data.relative_to(ROOT)))
    if problems:
        print("\n".join("FAIL " + p for p in problems))
        sys.exit(f"\nNot the public cut. Re-run in {sdir.relative_to(ROOT)}: python3 export.py --run {run} --public")

    committed = [p for p in tables if p.name.endswith(COMMITTED_SUFFIXES)]
    zipped = [p for p in tables if p not in committed]
    queries = sdir / "queries.json"
    dirty = bool(git("status", "--porcelain", "--", "benchmarks", "scripts"))
    if dirty:
        print("WARNING: uncommitted changes in benchmarks/ or scripts/; the manifest will record harness_dirty=true. "
              "Commit them first.")

    dest.mkdir(parents=True)
    out_files = []
    for p in committed:
        (dest / p.name).write_bytes(p.read_bytes())
        out_files.append(p.name)
    (dest / "scores.md").write_bytes(scores.read_bytes())
    (dest / "queries.json").write_bytes(queries.read_bytes())
    out_files += ["scores.md", "queries.json"]

    DIST.mkdir(exist_ok=True)
    zip_name = f"{suite}_{run}_public-data.zip"
    zip_path = DIST / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(zipped, key=lambda x: x.name):
            zi = zipfile.ZipInfo(f"{suite}_{run}/{p.name}", date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, p.read_bytes())
    assert not check_files([zip_path], "dist"), "zip failed the public-cut check"

    tag = f"{suite}/{run}"
    template = (ROOT / "templates" / "run-readme.md").read_text(encoding="utf-8")
    readme = (template.replace("{{suite}}", suite).replace("{{run}}", run).replace("{{tag}}", tag)
              .replace("{{zip_name}}", zip_name).replace("{{zip_sha256}}", sha256_file(zip_path))
              .replace("{{harness_commit}}", git("rev-parse", "HEAD") or "unknown")
              .replace("{{queries_sha256}}", sha256_file(queries))
              .replace("{{scores}}", scores.read_text(encoding="utf-8").strip()))
    (dest / "README.md").write_text(readme, encoding="utf-8")
    out_files.append("README.md")

    manifest = {
        "suite": suite, "run": run,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "harness_commit": git("rev-parse", "HEAD") or None, "harness_dirty": dirty,
        "queries_sha256": sha256_file(queries),
        "release": {"tag": tag, "assets": [{"name": zip_name, "bytes": zip_path.stat().st_size,
                                            "sha256": sha256_file(zip_path),
                                            "contents": sorted(p.name for p in zipped)}]},
        # README.md is hand-edited before commit, so it is deliberately not hashed here.
        "files": [{"name": n, "bytes": (dest / n).stat().st_size, "sha256": sha256_file(dest / n)}
                  for n in sorted(out_files) if n != "README.md"],
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    rel = dest.relative_to(ROOT)
    print(f"\nCreated {rel}/ and dist/{zip_name}\n\nNext (see AGENTS.md section 5, step 9 onward):")
    print(f"  1. Edit {rel}/README.md: resolve every TODO.")
    print(f"  2. python3 scripts/publish_run.py --check")
    print(f"  3. git add {rel} && git commit -m 'Publish {suite} {run}'")
    print(f"  4. After the commit is on main:\n     gh release create {tag} dist/{zip_name} --title '{suite} {run}' "
          f"--notes 'Public cut of {suite} run {run}. See {rel}/README.md.' --target main")
    print(f"  5. Add the run to the index in README.md and to CHANGELOG.md.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify every published run folder")
    ap.add_argument("--suite", help="suite folder name under benchmarks/, e.g. s1-event-recall")
    ap.add_argument("--run", help="run id, as passed to run.py, e.g. 2026-11-24")
    a = ap.parse_args()
    if a.check:
        return check_published()
    if not (a.suite and a.run):
        ap.error("give --suite and --run, or --check")
    return publish(a.suite, a.run)


if __name__ == "__main__":
    sys.exit(main())
