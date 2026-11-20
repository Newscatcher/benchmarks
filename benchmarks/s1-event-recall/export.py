"""Export one run to flat, raw tables: one row per returned result with every judge label, plus queries, events
or stories, per query-window metrics, calls and systems. Same numbers as score.py, rebuilt from
the run files so any aggregation can start from the rows.

Writes data/<run>/<file>.csv and data/<run>/benchmarks.sqlite (one table per CSV).

    python3 export.py --run <run> [--public]

--public drops every Exa row and Exa's per-query metrics (Exa stays aggregate-only in anything public) and writes to
data/<run>/ without snippets. The default export of your own run keeps everything.
"""
import argparse
import collections
import csv
import datetime as dt
import json
import math
import sqlite3
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent

SYSTEMS = [  # system, vendor, product, mode, settings, results requested, list price
    ("nc_low", "NewsCatcher", "News API /search", "effort=low", "collapse=story, default content_type=news", "S1 50, S2 10", "1 credit per call ($0.001)"),
    ("nc_medium", "NewsCatcher", "News API /search", "effort=medium", "collapse=story; the default effort", "S1 50, S2 10", "5 credits per call ($0.005)"),
    ("nc_high", "NewsCatcher", "News API /search", "effort=high", "collapse=story", "S1 50, S2 10", "10 credits per call ($0.010)"),
    ("nc_medium_en", "NewsCatcher", "News API /search", "effort=medium, languages=en", "S1 only: English results only", "S1 50", "5 credits per call ($0.005)"),
    ("exa_auto", "Exa", "/search", "type=auto", "category=news, published-date window; query 'news articles about {q}'", "S1 50, S2 10", "$7 per 1k calls up to 10 results + $1 per 1k results above 10"),
    ("exa_lite", "Exa", "/search", "type=lite", "same as exa_auto", "S1 50, S2 10", "$4 per 1k calls up to 10 results + $1 per 1k results above 10"),
    ("exa_deep_lite", "Exa", "/search", "type=deep-lite", "same as exa_auto; from the second run on", "S1 50, S2 10", "$12 per 1k calls up to 10 results + $1 per 1k results above 10"),
    ("exa_deep", "Exa", "/search", "type=deep", "same as exa_auto; from the second run on", "S1 50, S2 10", "$12 per 1k calls up to 10 results + $1 per 1k results above 10"),
    ("parallel_advanced", "Parallel", "/v1/search", "mode=advanced", "objective + search_queries, after_date = window start", "S1 20 (cap), S2 10", "$0.005 per call"),
    ("parallel_basic", "Parallel", "/v1/search", "mode=basic", "same as parallel_advanced", "S1 20 (cap), S2 10", "$0.005 per call"),
    ("firecrawl_news", "Firecrawl", "/v2/search", "sources=news", "no time filter for news; window applied at scoring", "S1 50, S2 10", "about $0.025 per call"),
    ("gnews", "Google News", "RSS", "when:1d/7d/30d, hl=en-US", "reference only: feeds the pool, not priced", "S1 up to 100, S2 20 pooled", "free"),
]
S1_DAYS = {"24h": 1, "7d": 7, "30d": 30}
CAP20 = {"parallel_advanced", "parallel_basic"}
S2_DAYS = {"24h": 1, "7d": 7}


def day(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def jl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


PUBLIC = False


def write(out, name, rows, cols, tables):
    if PUBLIC:  # article snippets and page descriptions stay with their publishers
        cols = [c for c in cols if c not in ("snippet_returned", "judge_input_snippet")]
    with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in cols})
    tables[name] = (cols, rows)
    print(f"  {name}.csv: {len(rows):,} rows")


def b(x):
    return None if x is None else int(bool(x))


def s1(run_id, tables, out, public):
    d = HERE
    run = d / "runs" / run_id
    meta = json.loads((run / "run.json").read_text())
    queries = {q["qid"]: q for q in json.loads((d / "queries.json").read_text())}
    mapping = json.loads((run / ".key" / "map.json").read_text())
    labels = {v["iid"]: v for v in jl(run / "judge" / "labels.jsonl")}
    groups = {v["pid"]: v["groups"] for v in jl(run / "judge" / "events.jsonl")}
    pools = {p["pid"]: {it["iid"]: it for it in p["items"]} for p in jl(run / "judge" / "pools.jsonl")}
    calls = jl(run / "calls.jsonl")
    called = {(c["qid"], c["window"]): c["called_at"] for c in calls}
    page_date = {}
    for url, p in json.loads((run / "pagecheck.json").read_text())["pages"].items():
        if day(p.get("date")):
            page_date[url] = day(p.get("date"))
    raw = {}

    def raw_res(s, pid):
        if (s, pid) not in raw:
            f = run / "raw" / s / f"{pid}.json"
            raw[(s, pid)] = json.loads(f.read_text())["results"] if f.exists() else []
        return raw[(s, pid)]

    systems = meta["systems"]
    keep = [s for s in systems if not (public and s.startswith("exa_"))]
    results, events_rows, metrics = [], [], []
    for pid in sorted(groups):
        qid, w = pid.split("__")
        q = queries[qid]
        start = dt.datetime.fromisoformat(called[(qid, w)]).date() - dt.timedelta(days=S1_DAYS[w] + 1)
        items = {iid: m for iid, m in mapping.items() if iid.startswith(pid + "#")}
        good, event, info = {}, {}, {}
        for iid, m in items.items():
            v = labels.get(iid, {})
            pds = [page_date[u] for u in m.get("urls", []) if u in page_date]
            d_used = min(pds) if pds else day(m.get("date"))
            src = "page" if pds else ("system" if d_used else "none")
            ok = v.get("on_topic") == "yes" and v.get("news") is True and (d_used is None or d_used >= start)
            good[iid] = ok
            ek = v.get("event_key")
            if ok and ek:
                event[iid] = f"{pid}:{groups[pid].get(ek, ek)}"
            info[iid] = (v, d_used, src)
        scored = sum(good.values()) >= 10
        pool_events = set(event.values())
        ranked = collections.defaultdict(list)
        for iid, m in items.items():
            for s, rank in m["hits"]:
                ranked[s].append((rank, iid))
        ev_rank = collections.defaultdict(dict)
        for s in systems:
            lst = sorted(ranked.get(s, []))
            seen = set()
            for rank, iid in lst:
                v, d_used, src = info[iid]
                ev = event.get(iid)
                first = repeat = 0
                if good[iid]:
                    key = ev or ("no key", iid)
                    first, repeat = int(key not in seen), int(key in seen)
                    seen.add(key)
                    if ev and rank <= 50:
                        ev_rank[ev].setdefault(s, rank)
                if s not in keep:
                    continue
                r = raw_res(s, pid)
                rr = r[rank - 1] if 0 < rank <= len(r) else {}
                pi = pools[pid].get(iid, {})
                results.append({
                    "benchmark": "S1", "run": run_id, "pid": pid, "qid": qid, "window": w, "query": q["query"],
                    "group": q["group"], "system": s, "rank": rank, "pool_item_id": iid,
                    "title": rr.get("title"), "source": rr.get("source"), "url": rr.get("url"),
                    "date_returned": (rr.get("date") or "")[:25] or None,
                    "snippet_returned": (rr.get("snippet") or "")[:400] or None,
                    "judge_input_title": pi.get("title"), "judge_input_source": pi.get("source"),
                    "judge_input_date": pi.get("date"),
                    "page_date": min([page_date[u] for u in items[iid].get("urls", []) if u in page_date], default=None),
                    "date_used": d_used, "date_source": src, "window_start": start,
                    "in_window": None if d_used is None else int(d_used >= start),
                    "judge_on_topic": v.get("on_topic"), "judge_news": b(v.get("news")) if "news" in v else None,
                    "judge_event_key": v.get("event_key"), "event_id": ev, "good": int(good[iid]),
                    "first_of_event": first, "repeat_of_event": repeat, "query_window_scored": int(scored)})
            # metrics, exactly as s1_score.py
            top = lambda k: lst[:k]
            def hits(k, distinct=True):
                if not distinct:
                    return sum(good[i] for _, i in top(k))
                return len({event.get(i, ("no key", i)) for _, i in top(k) if good[i]})
            ev50 = [event[i] for _, i in top(50) if i in event]
            ev20 = {event[i] for _, i in top(20) if i in event}
            n = len(top(50)) or 1
            if True:
                metrics.append({
                    "benchmark": "S1", "run": run_id, "pid": pid, "qid": qid, "window": w, "group": q["group"],
                    "system": s, "query_window_scored": int(scored), "good_in_pool": sum(good.values()),
                    "events_in_pool": len(pool_events), "returned": len(lst[:50]),
                    **{f"p_at_{k}": round(hits(k) / k, 4) for k in (10, 20, 50)},
                    **{f"p_at_{k}_article": round(hits(k, False) / k, 4) for k in (10, 20, 50)},
                    "recall_at_20": round(len(ev20) / len(pool_events), 4) if pool_events else 0,
                    "recall_at_50": round(len(set(ev50)) / len(pool_events), 4) if pool_events else 0,
                    "events_at_50": len(set(ev50)),
                    "repeat_share": round((len(ev50) - len(set(ev50))) / n, 4),
                    "non_news_share": round(sum(1 for _, i in top(50) if labels.get(i, {}).get("news") is False) / n, 4)})
                if s in CAP20:  # Parallel's public search returns at most 20: no top-50 metrics, as in s1_score.py
                    metrics[-1].update({"p_at_50": None, "p_at_50_article": None, "recall_at_50": None, "events_at_50": None})
        keys = collections.defaultdict(set)
        nitems = collections.Counter()
        for iid, ev in event.items():
            keys[ev].add(labels[iid]["event_key"])
            nitems[ev] += 1
        for ev in sorted(pool_events, key=lambda e: (len(e), e)):
            events_rows.append({"benchmark": "S1", "run": run_id, "pid": pid, "qid": qid, "window": w, "query": q["query"],
                                "group": q["group"], "event_id": ev, "event_keys": " || ".join(sorted(keys[ev])),
                                "good_pool_items": nitems[ev], "query_window_scored": int(scored),
                                "found_by_top50": ";".join(s for s in keep if s in ev_rank[ev]),
                                **{f"first_rank_{s}": ev_rank[ev].get(s) for s in keep}})
    qrows = [{"benchmark": "S1", "qid": k, "query": v["query"], "group": v["group"], "hit_definition": v.get("hit"),
              "windows": "24h;7d;30d"} for k, v in sorted(queries.items())]
    call_all = [{"benchmark": "S1", "run": run_id, **c} for c in calls]
    crow = [c for c in call_all if c["system"] in keep]
    rc = ["benchmark", "run", "pid", "qid", "window", "query", "group", "system", "rank", "pool_item_id", "title", "source",
          "url", "date_returned", "snippet_returned", "judge_input_title", "judge_input_source", "judge_input_date",
          "page_date", "date_used", "date_source", "window_start", "in_window", "judge_on_topic", "judge_news",
          "judge_event_key", "event_id", "good", "first_of_event", "repeat_of_event", "query_window_scored"]
    mc = ["benchmark", "run", "pid", "qid", "window", "group", "system", "query_window_scored", "good_in_pool",
          "events_in_pool", "returned", "p_at_10", "p_at_20", "p_at_50", "p_at_10_article", "p_at_20_article",
          "p_at_50_article", "recall_at_20", "recall_at_50", "events_at_50", "repeat_share", "non_news_share"]
    ec = ["benchmark", "run", "pid", "qid", "window", "query", "group", "event_id", "event_keys", "good_pool_items",
          "query_window_scored", "found_by_top50"] + [f"first_rank_{s}" for s in keep]
    write(out, "s1_queries", qrows, ["benchmark", "qid", "query", "group", "hit_definition", "windows"], tables)
    write(out, "s1_results", results, rc, tables)
    write(out, "s1_events", events_rows, ec, tables)
    write(out, "s1_metrics_per_query_window", [m for m in metrics if m["system"] in keep], mc, tables)
    write(out, "s1_calls", crow, ["benchmark", "run", "system", "qid", "window", "status", "n", "latency_s", "cost_usd",
                                  "called_at", "error"], tables)
    return metrics, call_all, systems



def summary(bench, metrics, calls, systems, cols, tables, out, extra=()):
    rows = []
    for s in systems:
        ms = [m for m in metrics if m["system"] == s and m["query_window_scored"]]
        cs = [c for c in calls if c["system"] == s and c["status"] == 200]
        if not ms:
            continue
        lat = sorted(c["latency_s"] for c in cs) or [None]
        usd = sum(c["cost_usd"] or 0 for c in cs)
        row = {"benchmark": bench, "system": s, "query_windows": len(ms), "calls_ok": len(cs),
               "latency_p50_s": lat[len(lat) // 2], "latency_p90_s": lat[int(len(lat) * .9)],
               "usd_total": round(usd, 4), "usd_per_call": round(usd / len(cs), 5) if cs and usd else None}
        for c in cols:
            vals = [m[c] for m in ms if m.get(c) is not None]
            row[c] = round(st.fmean(vals), 4) if vals else None
        if bench == "S1":  # recall over all events pooled across query-windows (micro); recall_at_50 is per search (macro)
            found = [m["events_at_50"] for m in ms if m.get("events_at_50") is not None]
            row["recall_at_50_all_events"] = (round(sum(found) / sum(m["events_in_pool"] for m in ms), 4)
                                              if len(found) == len(ms) else None)
        rows.append(row)
    allcols = list(cols)
    if bench == "S1" and "recall_at_50" in allcols:
        allcols.insert(allcols.index("recall_at_50") + 1, "recall_at_50_all_events")
    write(out, f"{bench.lower()}_summary_by_system", rows,
          ["benchmark", "system", "query_windows", "calls_ok", *allcols, "latency_p50_s", "latency_p90_s", "usd_total",
           "usd_per_call", *extra], tables)
    return rows


def main():
    global PUBLIC
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--public", action="store_true", help="no Exa rows, no snippets (the published cut)")
    ap.add_argument("--sqlite", action="store_true", help="also write benchmarks.sqlite")
    a = ap.parse_args()
    PUBLIC = a.public
    out = HERE / "data" / a.run
    out.mkdir(parents=True, exist_ok=True)
    tables = {}
    m, calls, systems = s1(a.run, tables, out, a.public)
    write(out, "systems", [dict(zip(["system", "vendor", "product", "mode", "settings", "results_requested", "list_price"], r))
                           for r in SYSTEMS if r[0] in systems], ["system", "vendor", "product", "mode", "settings",
                                                                   "results_requested", "list_price"], tables)
    summary("S1", m, calls, systems, ["p_at_10", "p_at_20", "p_at_50", "p_at_10_article", "p_at_20_article", "p_at_50_article", "recall_at_20", "recall_at_50", "events_at_50", "repeat_share", "non_news_share"], tables, out)
    if a.sqlite:
        db = out / "benchmarks.sqlite"
        db.unlink(missing_ok=True)
        con = sqlite3.connect(db)
        for name, (cs, rows) in tables.items():
            con.execute(f'CREATE TABLE "{name}" ({", ".join(chr(34) + c + chr(34) for c in cs)})')
            con.executemany(f'INSERT INTO "{name}" VALUES ({", ".join("?" * len(cs))})',
                            [[(str(r[c]) if isinstance(r.get(c), dt.date) else r.get(c)) for c in cs] for r in rows])
        con.commit()
        con.close()


if __name__ == "__main__":
    main()
