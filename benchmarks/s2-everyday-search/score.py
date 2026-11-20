"""S2 scoring from the judge's grades and story groups.

A result's gain is its grade (0-3) if it is news and dated inside the window (the page's own date where fetched,
else the system's; one day of slack), else 0. Each story counts once: within a system's top 10, a later result
about a story already shown gains 0. Per system and query-window:
- nDCG@10: DCG = sum (2^gain - 1) / log2(rank + 1); the ideal ranking takes the best grade of each distinct story in
  the whole pool (every system's top 10 + Google News's top 20);
- P@10: distinct grade-3 stories in the top 10 / 10;
- for one-story queries, found@1 and found@10 (the target story, in window); for questions, answered@1 and
  answered@10 ("yes" from the judge);
- fresh: share of dated top-10 results inside the window; non-news share.
Differences vs NC medium carry a paired bootstrap 95% interval over query-windows.

    python3 score.py --run 2026-11-18 [--json out.json] > runs/2026-11-18/scores.md
"""
import argparse
import collections
import datetime as dt
import json
import math
import random
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAYS = {"24h": 1, "7d": 7}
BASE = "nc_medium"
ORDER = ["nc_low", "nc_medium", "nc_high", "exa_lite", "exa_auto", "exa_deep_lite", "exa_deep", "parallel_basic", "parallel_advanced",
         "firecrawl_news", "gnews"]


def boot(diffs, n=10000, seed=7):
    if not diffs:
        return 0, 0, 0
    rng = random.Random(seed)
    m = sorted(st.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return st.fmean(diffs), m[int(.025 * n)], m[int(.975 * n)]


def day(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--json")
    ap.add_argument("--count-repeats", action="store_true", help="article-level: repeats of a story keep their grade")
    a = ap.parse_args()
    out = HERE / "runs" / a.run
    run = json.loads((out / "run.json").read_text())
    queries = {q["qid"]: q for q in json.loads((HERE / "queries.json").read_text())}
    mapping = json.loads((out / ".key" / "map.json").read_text())
    labels = {json.loads(l)["iid"]: json.loads(l) for l in open(out / "judge" / "labels.jsonl")}
    groups = {json.loads(l)["pid"]: json.loads(l)["groups"] for l in open(out / "judge" / "events.jsonl")}
    calls = [json.loads(l) for l in open(out / "calls.jsonl")]
    called = {(c["qid"], c["window"]): c["called_at"] for c in calls}
    # A system with no successful call (for example, out of credits) is left out, not scored as zero.
    systems = [s for s in ORDER if s in run["systems"] and any(c["system"] == s and c["status"] == 200 for c in calls)]
    by_pid = collections.defaultdict(list)
    for iid, m in mapping.items():
        by_pid[iid.split("#")[0]].append((iid, m))

    per = collections.defaultdict(dict)
    skipped = []
    for pid in run["pids"]:
        qid, w = pid.split("__")
        q = queries[qid]
        start = dt.datetime.fromisoformat(called[(qid, w)]).date() - dt.timedelta(days=DAYS[w] + 1)
        gain, story, inwin, news, info = {}, {}, {}, {}, {}
        ranked = collections.defaultdict(list)
        for iid, m in by_pid[pid]:
            v = labels.get(iid, {})
            d = day(m.get("page_date")) or day(m.get("date"))
            ok_date = d is None or d >= start
            inwin[iid] = None if d is None else d >= start
            news[iid] = v.get("news") is True
            gain[iid] = int(v.get("grade") or 0) if (news[iid] and ok_date) else 0
            k = v.get("story_key")
            story[iid] = str(groups.get(pid, {}).get(k, k)) if k else f"item:{iid}"
            info[iid] = v
            for s, rank in m["hits"]:
                ranked[s].append((rank, iid))
        best = {}
        for iid, g in gain.items():
            best[story[iid]] = max(best.get(story[iid], 0), g)
        # distinct-story ideal: the best grade of each story; article-level ideal: every result's grade
        ideal = sorted((g for g in (gain.values() if a.count_repeats else best.values()) if g > 0), reverse=True)[:10]
        idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
        if idcg == 0:
            skipped.append(pid)
            continue
        for s in systems:
            top = [iid for _, iid in sorted(ranked.get(s, []))][:10]
            seen, rels, reps = set(), [], 0
            for iid in top:
                rep = story[iid] in seen and gain[iid] > 0
                reps += rep
                rels.append(gain[iid] if a.count_repeats or not rep else 0)
                seen.add(story[iid])
            dcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(rels))
            dated = [inwin[i] for i in top if inwin[i] is not None]
            m = {"nDCG@10": dcg / idcg, "P@10": sum(1 for g in rels if g == 3) / 10,
                 "fresh": sum(dated) / len(dated) if dated else None,
                 "non-news": sum(1 for i in top if not news[i]) / len(top) if top else None,
                 "repeats": reps / len(top) if top else None, "returned": len(top)}
            if q["type"] == "story":
                hit = [r for r, i in enumerate(top, 1) if info[i].get("story_match") is True and inwin[i] is not False]
                m["found@1"], m["found@10"] = float(bool(hit and hit[0] == 1)), float(bool(hit))
            if q["type"] == "question":
                hit = [r for r, i in enumerate(top, 1) if info[i].get("answers") == "yes" and inwin[i] is not False]
                m["answered@1"], m["answered@10"] = float(bool(hit and hit[0] == 1)), float(bool(hit))
            per[pid][s] = m

    pids = sorted(per)

    def mean(ps, s, k):
        vals = [per[p][s][k] for p in ps if s in per[p] and per[p][s].get(k) is not None]
        return st.fmean(vals) if vals else None

    def fmt(x, pct=False):
        return "n/a" if x is None else (f"{x:.0%}" if pct else f"{x:.2f}")

    def table(ps, title):
        L = [f"### {title} ({len(ps)} query-windows)\n",
             "| System | nDCG@10 | P@10 | repeats | fresh | non-news | returned |", "|---|---|---|---|---|---|---|"]
        for s in systems:
            L.append(f"| {s} | {fmt(mean(ps, s, 'nDCG@10'))} | {fmt(mean(ps, s, 'P@10'))} | {fmt(mean(ps, s, 'repeats'), 1)} | "
                     f"{fmt(mean(ps, s, 'fresh'), 1)} | {fmt(mean(ps, s, 'non-news'), 1)} | {mean(ps, s, 'returned') or 0:.1f} |")
        if BASE not in systems:  # e.g. a run without a NewsCatcher key: no paired differences
            return "\n".join(L) + "\n"
        L += ["", f"Differences vs {BASE} (mean [95% CI]):", "", "| System | nDCG@10 | P@10 |", "|---|---|---|"]
        for s in systems:
            if s == BASE:
                continue
            cells = []
            for k in ("nDCG@10", "P@10"):
                mu, lo, hi = boot([per[p][BASE][k] - per[p][s][k] for p in ps if s in per[p] and BASE in per[p]])
                cells.append(f"{mu:+.2f} [{lo:+.2f}, {hi:+.2f}]")
            L.append(f"| {BASE} − {s} | " + " | ".join(cells) + " |")
        return "\n".join(L) + "\n"

    print(f"# S2 scores, run {a.run}\n")
    print(f"Query-windows: {len(run['pids'])}; scored: {len(pids)}; skipped (no relevant result in the pool): "
          f"{len(skipped)} {skipped}\n")
    print(table(pids, "All query-windows"))
    for t in ("entity", "topic", "story", "question", "non_english"):
        ps = [p for p in pids if queries[p.split('__')[0]]["type"] == t]
        if ps:
            print(table(ps, f"Type: {t}"))
    for w in DAYS:
        ps = [p for p in pids if p.endswith("__" + w) and queries[p.split('__')[0]]["type"] in ("entity", "topic")]
        if ps:
            print(table(ps, f"Entity and topic queries, window {w}"))
    sp = [p for p in pids if queries[p.split('__')[0]]["type"] == "story"]
    qp = [p for p in pids if queries[p.split('__')[0]]["type"] == "question"]
    print(f"### Story found and question answered\n\n| System | story found@1 | story found@10 ({len(sp)}) | "
          f"answered@1 | answered@10 ({len(qp)}) |\n|---|---|---|---|---|")
    for s in systems:
        print(f"| {s} | {fmt(mean(sp, s, 'found@1'), 1)} | {fmt(mean(sp, s, 'found@10'), 1)} | "
              f"{fmt(mean(qp, s, 'answered@1'), 1)} | {fmt(mean(qp, s, 'answered@10'), 1)} |")
    print("\n### Latency and price\n\n| System | calls | p50 s | p90 s | $ per search | $ per 1k grade-3 stories |\n"
          "|---|---|---|---|---|---|")
    for s in systems:
        cs = [c for c in calls if c["system"] == s and c["status"] == 200]
        if not cs:
            continue
        lat = sorted(c["latency_s"] for c in cs)
        usd = sum(c["cost_usd"] or 0 for c in cs)
        g3 = sum(round(per[p][s]["P@10"] * 10) for p in pids if s in per[p])
        print(f"| {s} | {len(cs)} | {lat[len(lat) // 2]:.2f} | {lat[int(len(lat) * .9)]:.2f} | "
              f"{'$%.4f' % (usd / len(cs)) if usd else 'n/a'} | {'$%.2f' % (usd / g3 * 1000) if usd and g3 else 'n/a'} |")
    if a.json:
        Path(a.json).write_text(json.dumps({"run": a.run, "per": per, "skipped": skipped}, indent=0))


if __name__ == "__main__":
    main()
