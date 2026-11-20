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


def s2(run_id, tables, out, public):
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
    systems = [s for s in meta["systems"] if any(c["system"] == s and c["status"] == 200 for c in calls)]
    keep = [s for s in systems if not (public and s.startswith("exa_"))]
    raw = {}

    def raw_res(s, pid):
        if (s, pid) not in raw:
            f = run / "raw" / s / f"{pid}.json"
            raw[(s, pid)] = json.loads(f.read_text())["results"] if f.exists() else []
        return raw[(s, pid)]

    results, stories, metrics = [], [], []
    for pid in meta["pids"]:
        qid, w = pid.split("__")
        q = queries[qid]
        start = dt.datetime.fromisoformat(called[(qid, w)]).date() - dt.timedelta(days=S2_DAYS[w] + 1)
        items = {iid: m for iid, m in mapping.items() if iid.split("#")[0] == pid}
        gain, story, inwin, news, info, dused = {}, {}, {}, {}, {}, {}
        ranked = collections.defaultdict(list)
        for iid, m in items.items():
            v = labels.get(iid, {})
            dd = day(m.get("page_date")) or day(m.get("date"))
            dused[iid] = dd
            inwin[iid] = None if dd is None else dd >= start
            news[iid] = v.get("news") is True
            gain[iid] = int(v.get("grade") or 0) if (news[iid] and (dd is None or dd >= start)) else 0
            k = v.get("story_key")
            story[iid] = f"{pid}:{groups.get(pid, {}).get(k, k)}" if k else f"item:{iid}"
            info[iid] = v
            for s, rank in m["hits"]:
                ranked[s].append((rank, iid))
        best = {}
        for iid, g in gain.items():
            best[story[iid]] = max(best.get(story[iid], 0), g)
        ideal_d = sorted((g for g in best.values() if g > 0), reverse=True)[:10]
        ideal_a = sorted((g for g in gain.values() if g > 0), reverse=True)[:10]
        dcg = lambda gs: sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gs))
        idcg_d, idcg_a = dcg(ideal_d), dcg(ideal_a)
        scored = idcg_d > 0
        srank = collections.defaultdict(dict)
        for s in systems:
            lst = sorted(ranked.get(s, []))
            seen, rels_d, rels_a, reps = set(), [], [], 0
            for rank, iid in lst:
                in_top = rank <= 10
                rep = story[iid] in seen and gain[iid] > 0 if in_top else None
                if in_top:
                    reps += rep
                    rels_d.append(0 if rep else gain[iid])
                    rels_a.append(gain[iid])
                    seen.add(story[iid])
                    if gain[iid] > 0:
                        srank[story[iid]].setdefault(s, rank)
                if s not in keep:
                    continue
                v = info[iid]
                r = raw_res(s, pid)
                rr = r[rank - 1] if 0 < rank <= len(r) else {}
                pi = pools[pid].get(iid, {})
                results.append({
                    "benchmark": "S2", "run": run_id, "pid": pid, "qid": qid, "window": w, "query": q["query"],
                    "query_type": q["type"], "lang": q.get("lang"), "system": s, "rank": rank, "in_top10": int(in_top),
                    "pool_item_id": iid, "title": rr.get("title"), "source": rr.get("source"), "url": rr.get("url"),
                    "date_returned": (rr.get("date") or "")[:25] or None,
                    "snippet_returned": (rr.get("snippet") or "")[:400] or None,
                    "judge_input_title": pi.get("title"), "judge_input_source": pi.get("source"),
                    "judge_input_date": pi.get("date"), "judge_input_snippet": pi.get("snippet"),
                    "page_date": items[iid].get("page_date"), "date_used": dused[iid], "window_start": start,
                    "in_window": None if inwin[iid] is None else int(inwin[iid]),
                    "judge_grade": v.get("grade"), "judge_news": b(v.get("news")) if "news" in v else None,
                    "judge_story_key": v.get("story_key"), "story_id": story[iid] if v.get("story_key") else None,
                    "judge_story_match": b(v.get("story_match")) if "story_match" in v else None,
                    "judge_answers": v.get("answers"), "gain": gain[iid],
                    "repeat_of_story": None if rep is None else int(rep),
                    "gain_counted": (0 if rep else gain[iid]) if in_top else None, "query_window_scored": int(scored)})
            top = [iid for _, iid in lst][:10]
            dated = [inwin[i] for i in top if inwin[i] is not None]
            m = {"benchmark": "S2", "run": run_id, "pid": pid, "qid": qid, "window": w, "query_type": q["type"],
                 "lang": q.get("lang"), "system": s, "query_window_scored": int(scored), "returned": len(top),
                 "ndcg_at_10": round(dcg(rels_d) / idcg_d, 4) if scored else None,
                 "ndcg_at_10_article": round(dcg(rels_a) / idcg_a, 4) if idcg_a else None,
                 "p_at_10": sum(1 for g in rels_d if g == 3) / 10, "p_at_10_article": sum(1 for g in rels_a if g == 3) / 10,
                 "dcg_at_10": round(dcg(rels_d), 4), "ideal_dcg_at_10": round(idcg_d, 4),
                 "repeat_share": round(reps / len(top), 4) if top else None,
                 "fresh_share": round(sum(dated) / len(dated), 4) if dated else None,
                 "non_news_share": round(sum(1 for i in top if not news[i]) / len(top), 4) if top else None}
            if q["type"] == "story":
                hit = [r for r, i in enumerate(top, 1) if info[i].get("story_match") is True and inwin[i] is not False]
                m["found_at_1"], m["found_at_10"] = int(bool(hit and hit[0] == 1)), int(bool(hit))
            if q["type"] == "question":
                hit = [r for r, i in enumerate(top, 1) if info[i].get("answers") == "yes" and inwin[i] is not False]
                m["answered_at_1"], m["answered_at_10"] = int(bool(hit and hit[0] == 1)), int(bool(hit))
            metrics.append(m)
        keys = collections.defaultdict(set)
        for iid in items:
            if labels.get(iid, {}).get("story_key"):
                keys[story[iid]].add(labels[iid]["story_key"])
        # every story with a positive gain, including single unkeyed items (grade 1), so the ideal DCG can be rebuilt
        sids = set(keys) | {story[i] for i in items if gain[i] > 0}
        for sid in sorted(sids, key=lambda e: (len(e), e)):
            stories.append({"benchmark": "S2", "run": run_id, "pid": pid, "qid": qid, "window": w, "query": q["query"],
                            "query_type": q["type"], "story_id": sid, "story_keys": " || ".join(sorted(keys.get(sid, ()))),
                            "best_gain": best.get(sid, 0), "query_window_scored": int(scored),
                            "found_by_top10": ";".join(s for s in keep if s in srank[sid]),
                            **{f"first_rank_{s}": srank[sid].get(s) for s in keep}})
    qrows = [{"benchmark": "S2", "qid": k, "query_type": v["type"], "query": v["query"], "lang": v.get("lang"),
              "windows": ";".join(v["windows"]), "what_counts_as_good": v.get("good"), "gold": v.get("gold"),
              "event_date": v.get("event_date"), "gold_source": v.get("source")} for k, v in sorted(queries.items())]
    call_all = [{"benchmark": "S2", "run": run_id, **c} for c in calls]
    crow = [c for c in call_all if c["system"] in keep]
    rc = ["benchmark", "run", "pid", "qid", "window", "query", "query_type", "lang", "system", "rank", "in_top10",
          "pool_item_id", "title", "source", "url", "date_returned", "snippet_returned", "judge_input_title",
          "judge_input_source", "judge_input_date", "judge_input_snippet", "page_date", "date_used", "window_start",
          "in_window", "judge_grade", "judge_news", "judge_story_key", "story_id", "judge_story_match", "judge_answers",
          "gain", "repeat_of_story", "gain_counted", "query_window_scored"]
    mc = ["benchmark", "run", "pid", "qid", "window", "query_type", "lang", "system", "query_window_scored", "returned",
          "ndcg_at_10", "ndcg_at_10_article", "p_at_10", "p_at_10_article", "dcg_at_10", "ideal_dcg_at_10",
          "repeat_share", "fresh_share", "non_news_share", "found_at_1", "found_at_10", "answered_at_1", "answered_at_10"]
    sc = ["benchmark", "run", "pid", "qid", "window", "query", "query_type", "story_id", "story_keys", "best_gain",
          "query_window_scored", "found_by_top10"] + [f"first_rank_{s}" for s in keep]
    write(out, "s2_queries", qrows, ["benchmark", "qid", "query_type", "query", "lang", "windows", "what_counts_as_good",
                                     "gold", "event_date", "gold_source"], tables)
    write(out, "s2_results", results, rc, tables)
    write(out, "s2_stories", stories, sc, tables)
    write(out, "s2_metrics_per_query_window", [m for m in metrics if m["system"] in keep], mc, tables)
    write(out, "s2_calls", crow, ["benchmark", "run", "system", "qid", "window", "status", "n", "latency_s", "cost_usd",
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
    m, calls, systems = s2(a.run, tables, out, a.public)
    write(out, "systems", [dict(zip(["system", "vendor", "product", "mode", "settings", "results_requested", "list_price"], r))
                           for r in SYSTEMS if r[0] in systems], ["system", "vendor", "product", "mode", "settings",
                                                                   "results_requested", "list_price"], tables)
    summary("S2", m, calls, systems, ["ndcg_at_10", "ndcg_at_10_article", "p_at_10", "p_at_10_article", "repeat_share", "fresh_share", "non_news_share", "found_at_1", "found_at_10", "answered_at_1", "answered_at_10"], tables, out)
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
