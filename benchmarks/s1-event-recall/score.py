"""S1 scoring from the judge's labels and event groups.

Good result = on topic ("yes"), news, dated inside the window (a day of slack). Per system and query-window:
P@10, P@20, P@50 (missing slots count as misses), recall@50 = distinct good events in the system's top 50 / distinct
good events in the whole pool (every system's top 50 + Google News's top 100), distinct events@50, repeat and
non-news shares. A query-window counts only if its pool holds at least 10 good results. Differences vs NewsCatcher
medium carry a paired bootstrap 95% interval over query-windows.

    python3 score.py --run 2026-11-24 > runs/2026-11-24/scores.md
"""
import argparse
import collections
import datetime as dt
import json
import random
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAYS = {"24h": 1, "7d": 7, "30d": 30}
METRICS = ["P@10", "P@20", "P@50", "recall@20", "recall@50", "events@50", "repeats", "non-news"]
BASE = "nc_medium"
CAP20 = {"parallel_advanced", "parallel_basic"}  # public modes cap at 20 results: no P@50 / recall@50


def boot(diffs, n=10000, seed=7):
    if not diffs:
        return (0, 0, 0)
    rng = random.Random(seed)
    means = sorted(st.fmean(rng.choices(diffs, k=len(diffs))) for _ in range(n))
    return st.fmean(diffs), means[int(0.025 * n)], means[int(0.975 * n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--min-good", type=int, default=10)
    ap.add_argument("--claimed-dates", action="store_true", help="window check on the systems' dates only")
    # Headline (decided 2026-11-18): P@k counts distinct events. A repeat of an event already higher in the list is
    # a miss. --count-repeats gives the article-level P@k of the first write-up.
    ap.add_argument("--count-repeats", action="store_true", help="article-level P@k: every good result counts")
    ap.add_argument("--unique", action="store_true", help=argparse.SUPPRESS)  # the default now; kept for old commands
    ap.add_argument("--dump", help="also write per query-window metrics as JSON")
    a = ap.parse_args()
    a.unique = not a.count_repeats
    out = HERE / "runs" / a.run
    run = json.loads((out / "run.json").read_text())
    queries = {q["qid"]: q for q in json.loads((HERE / "queries.json").read_text())}
    mapping = json.loads((out / ".key" / "map.json").read_text())
    labels = {json.loads(l)["iid"]: json.loads(l) for l in open(out / "judge" / "labels.jsonl")}
    groups = {json.loads(l)["pid"]: json.loads(l)["groups"] for l in open(out / "judge" / "events.jsonl")}
    calls = [json.loads(l) for l in open(out / "calls.jsonl")]
    called = {(c["qid"], c["window"]): c["called_at"] for c in calls}
    # Window membership uses the page's own publication date where the page check found one (systems can label old
    # articles as recent); otherwise the date the systems reported. --claimed-dates turns this off.
    page_date = {}
    pc = out / "pagecheck.json"
    if pc.exists() and not a.claimed_dates:
        for url, p in json.loads(pc.read_text())["pages"].items():
            try:
                page_date[url] = dt.date.fromisoformat(str(p.get("date"))[:10])
            except ValueError:
                pass
    systems = [s for s in run["systems"]]
    scored = [s for s in systems if s != "gnews"] + (["gnews"] if "gnews" in systems else [])

    per = collections.defaultdict(dict)   # pid -> system -> metrics
    good_count, dropped = {}, []
    for pid in groups:
        qid, w = pid.split("__")
        start = dt.datetime.fromisoformat(called[(qid, w)]).date() - dt.timedelta(days=DAYS[w] + 1)
        ranked = collections.defaultdict(list)
        good, event = {}, {}
        for iid, m in mapping.items():
            if not iid.startswith(pid + "#"):
                continue
            v = labels.get(iid, {})
            pds = [page_date[u] for u in m.get("urls", []) if u in page_date]
            d = min(pds) if pds else (dt.date.fromisoformat(m["date"]) if m.get("date") else None)
            ok = v.get("on_topic") == "yes" and v.get("news") is True and (d is None or d >= start)
            good[iid] = ok
            if ok and v.get("event_key"):
                event[iid] = groups[pid].get(v["event_key"], v["event_key"])
            for s, rank in m["hits"]:
                ranked[s].append((rank, iid, v.get("news") is not False))
        pool_events = {event[i] for i in event}
        good_count[pid] = sum(good.values())
        if good_count[pid] < a.min_good:
            dropped.append(pid)
            continue
        for s in scored:
            lst = [x for x in sorted(ranked.get(s, []))]
            top = lambda k: lst[:k]
            def hits(k):
                if not a.unique:
                    return sum(good[i] for _, i, _ in top(k))
                seen = set()  # --unique: only the first good result of each event counts
                for _, i, _ in top(k):
                    if good[i]:
                        seen.add(event.get(i, ("no key", i)))
                return len(seen)
            m = {f"P@{k}": hits(k) / k for k in (10, 20, 50)}
            ev50 = [event[i] for _, i, _ in top(50) if i in event]
            ev20 = {event[i] for _, i, _ in top(20) if i in event}
            m["recall@20"] = len(ev20) / len(pool_events) if pool_events else 0
            m["recall@50"] = len(set(ev50)) / len(pool_events) if pool_events else 0
            m["events@50"] = len(set(ev50))
            n = len(top(50)) or 1
            m["repeats"] = (len(ev50) - len(set(ev50))) / n
            m["non-news"] = sum(1 for _, _, news in top(50) if not news) / n
            m["returned"] = len(lst[:50])
            per[pid][s] = m

    def table(pids, title):
        lines = [f"### {title} ({len(pids)} query-windows)", "",
                 "| System | " + " | ".join(METRICS) + " | returned |", "|" + "---|" * (len(METRICS) + 2)]
        for s in scored:
            vals = [per[p][s] for p in pids if s in per[p]]
            if not vals:
                continue
            cells = []
            for k in METRICS:
                if s in CAP20 and k in ("P@50", "recall@50", "events@50"):
                    cells.append("n/a (cap 20)")
                    continue
                mean = st.fmean(v[k] for v in vals)
                cells.append(f"{mean:.1f}" if k == "events@50" else f"{mean:.2f}")
            lines.append(f"| {s} | " + " | ".join(cells) + f" | {st.fmean(v['returned'] for v in vals):.0f} |")
        lines += ["", f"Differences vs {BASE} (mean [95% CI]):", "",
                  "| System | P@10 | P@20 | P@50 | recall@20 | recall@50 |", "|---|---|---|---|---|---|"]
        for s in scored:
            if s == BASE:
                continue
            cells = []
            for k in ("P@10", "P@20", "P@50", "recall@20", "recall@50"):
                if s in CAP20 and k in ("P@50", "recall@50"):
                    cells.append("n/a")
                    continue
                diffs = [per[p][BASE][k] - per[p][s][k] for p in pids if s in per[p] and BASE in per[p]]
                mu, lo, hi = boot(diffs)
                cells.append(f"{mu:+.2f} [{lo:+.2f}, {hi:+.2f}]")
            lines.append(f"| {BASE} − {s} | " + " | ".join(cells) + " |")
        return "\n".join(lines) + "\n"

    pids = sorted(per)
    if a.dump:
        Path(a.dump).write_text(json.dumps({p: per[p] for p in pids}, indent=0))
    print(f"# S1 scores, run {a.run}" + (" (each distinct event counted once in P@k)" if a.unique else "") + "\n")
    print(f"Pools judged: {len(groups)}; scored: {len(pids)}; dropped (< {a.min_good} good results): "
          f"{len(dropped)} {dropped}\n")
    print(table(pids, "All windows"))
    for w in DAYS:
        ws = [p for p in pids if p.endswith("__" + w)]
        if ws:
            print(table(ws, f"Window {w}"))
    by_group = collections.defaultdict(list)
    for p in pids:
        by_group[queries[p.split("__")[0]]["group"]].append(p)
    print("### Recall@50 by query group\n\n| Group | n | " + " | ".join(scored) + " |\n|" + "---|" * (len(scored) + 2))
    for g, ps in sorted(by_group.items()):
        print(f"| {g} | {len(ps)} | " + " | ".join(
            f"{st.fmean(per[p][s]['recall@50'] for p in ps if s in per[p]):.2f}" for s in scored) + " |")
    print("\n### Latency and price\n\n| System | calls | p50 s | p90 s | $ total | $ per 1k good results |\n|---|---|---|---|---|---|")
    goods = collections.Counter()
    for p in pids:
        for s in scored:
            goods[s] += round(per[p][s]["P@50"] * 50)
    for s in scored:
        cs = [c for c in calls if c["system"] == s and c["status"] == 200]
        if not cs:
            continue
        lat = sorted(c["latency_s"] for c in cs)
        usd = sum(c["cost_usd"] or 0 for c in cs)
        per_k = f"${usd / goods[s] * 1000:.2f}" if goods[s] and usd else "n/a"
        print(f"| {s} | {len(cs)} | {lat[len(lat) // 2]:.2f} | {lat[int(len(lat) * 0.9)]:.2f} | ${usd:.2f} | {per_k} |")


if __name__ == "__main__":
    main()
