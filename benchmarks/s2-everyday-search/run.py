"""S2 runner: everyday news search. Every query in each of its windows, every system at depth 10, all systems for
one query-window called at the same moment.

Reuses S1's vendor calls and settings (lib/clients.py, SYSTEMS.md) with DEPTH = 10: NewsCatcher
/search low, medium and high (collapse=story); Exa auto and lite (news category, date filter); Parallel advanced
and basic (10 results); Firecrawl news; Google News RSS as the reference (top 20 pooled). Keys come from NC_KEY,
EXA_KEY, PARALLEL_KEY and FIRECRAWL_KEY; they are never printed or saved.

Writes runs/<run>/raw/<system>/<qid>__<window>.json, runs/<run>/calls.jsonl and runs/<run>/run.json.

    python3 run.py --run 2026-11-18 [--queries s2_01,s2_31] [--systems nc_medium,exa_lite]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import clients as S1  # noqa: E402

S1.DEPTH = 10


def parallel10(mode):
    def call(q, win):
        now = dt.datetime.now(dt.timezone.utc)
        body = {"objective": f"Find news articles about {q} published in the last {S1.WINDOWS[win][4]}.",
                "search_queries": [q], "mode": mode,
                "advanced_settings": {"max_results": 10, "source_policy": {
                    "after_date": (now - dt.timedelta(days=S1.WINDOWS[win][1])).date().isoformat()}}}
        s, b, t = S1.http("POST", "https://api.parallel.ai/v1/search", {"x-api-key": S1.KEYS["PARALLEL_KEY"]}, body)
        d = json.loads(b) if s == 200 else {}
        res = [{"title": r.get("title"), "url": r.get("url"), "source": urllib.parse.urlparse(r.get("url") or "").netloc,
                "date": r.get("publish_date"), "snippet": " ".join(r.get("excerpts") or [])[:400] or None,
                "story": None} for r in d.get("results") or []]
        return s, res, t, 0.005 if s == 200 else 0, (None if s == 200 else S1.red(b[:300]))
    return call


SYSTEMS = {"nc_low": S1.nc("low"), "nc_medium": S1.nc("medium"), "nc_high": S1.nc("high"),
           "exa_auto": S1.exa("auto"), "exa_lite": S1.exa("lite"), "exa_deep_lite": S1.exa("deep-lite"),
           "exa_deep": S1.exa("deep"),
           "parallel_advanced": parallel10("advanced"), "parallel_basic": parallel10("basic"),
           "firecrawl_news": S1.firecrawl("news"), "gnews": S1.gnews}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--queries")
    ap.add_argument("--systems")
    a = ap.parse_args()
    need = {"nc": "NC_KEY", "exa": "EXA_KEY", "parallel": "PARALLEL_KEY", "firecrawl": "FIRECRAWL_KEY"}
    systems = {s: SYSTEMS[s] for s in a.systems.split(",")} if a.systems else SYSTEMS
    skipped = [s for s in systems if s.split("_")[0] in need and not S1.KEYS[need[s.split("_")[0]]]]
    systems = {s: f for s, f in systems.items() if s not in skipped}
    if skipped:
        print("skipped (no key):", ", ".join(skipped), flush=True)
    out = HERE / "runs" / a.run
    queries = json.loads((HERE / "queries.json").read_text())
    if a.queries:
        queries = [q for q in queries if q["qid"] in a.queries.split(",")]
    for s in systems:
        (out / "raw" / s).mkdir(parents=True, exist_ok=True)
    pids = [f"{q['qid']}__{w}" for q in queries for w in q["windows"]]
    (out / "run.json").write_text(json.dumps({"run": a.run, "started": dt.datetime.now(dt.timezone.utc).isoformat(),
                                              "systems": list(systems), "depth": S1.DEPTH, "pids": pids}, indent=1))
    log = open(out / "calls.jsonl", "a")
    with cf.ThreadPoolExecutor(max_workers=len(systems)) as ex:
        for q in queries:
            for w in q["windows"]:
                todo = {s: fn for s, fn in systems.items() if not (out / "raw" / s / f"{q['qid']}__{w}.json").exists()}
                at = dt.datetime.now(dt.timezone.utc).isoformat()
                futs = {s: ex.submit(fn, q["query"], w) for s, fn in todo.items()}
                for s, f in futs.items():
                    status, res, secs, cost, err = f.result()
                    rec = {"system": s, "qid": q["qid"], "window": w, "status": status, "n": len(res),
                           "latency_s": round(secs, 3), "cost_usd": cost, "called_at": at, "error": err}
                    log.write(json.dumps(rec) + "\n")
                    log.flush()
                    if status == 200:
                        (out / "raw" / s / f"{q['qid']}__{w}.json").write_text(
                            json.dumps({**rec, "results": res}, ensure_ascii=False))
                print(at[11:19], q["qid"], w, " ".join(f"{s}:{len(futs[s].result()[1])}" for s in futs), flush=True)


if __name__ == "__main__":
    main()
