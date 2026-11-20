"""S1 judge: labels every pooled item blind, then groups event keys into distinct events, per query-window.

Pass 1, batches of 20: on_topic (yes / partly / no) for the query's event class, news (true/false), and an event key
("Company | event | detail") for on-topic news. Pass 2, per pool: groups event keys that name the same real-world
event. Model: Claude Opus 5.5 via OpenRouter (OPENROUTER_API_KEY). Resumable. Set OPENROUTER_API_KEY, then:

    python3 judge.py --run 2026-11-24 [--model anthropic/claude-opus-5.5]
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KEY = os.environ.get("OPENROUTER_API_KEY", "")
LOCK = threading.Lock()
USAGE = {"in": 0, "out": 0, "calls": 0}

LABEL_SYS = """You judge news search results for a benchmark. The user searched for a CLASS of events and wants every \
real instance. For each item (title, source site, date) decide:
- on_topic: "yes" if the item reports one instance of the class as defined; "partly" if it is related but not a \
clear instance (an analysis, a roundup, a rumour, a wrong sector or region); "no" otherwise.
- news: true if it is a news article or press release reporting something that happened; false for listings, \
directories, product or company pages, job ads, stock-quote pages, explainers, opinion with no event, SEO pages.
- event_key: only when on_topic is "yes" and news is true: "<main organisation> | <event> | <key detail>", e.g. \
"Bharat Semi | seed round | $24M". Use the organisation's common name. Otherwise null.
Judge only from the given fields. Answer with a JSON array, one object per item: \
{"iid": ..., "on_topic": ..., "news": ..., "event_key": ...}."""

MERGE_SYS = """You group event keys from news search results. Keys that describe the SAME real-world event (the same \
organisation and the same deal, appointment, launch, incident or filing, even if worded differently or with a \
different detail) get the same group number. Different events get different numbers. Answer with a JSON object \
mapping every key exactly as given to an integer group: {"<key>": 1, ...}."""


def chat(model, system, user, max_tokens=8000):
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    for attempt in range(6):
        try:
            req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", method="POST",
                                         data=json.dumps(body).encode(),
                                         headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            u = d.get("usage") or {}
            with LOCK:
                USAGE["in"] += u.get("prompt_tokens", 0)
                USAGE["out"] += u.get("completion_tokens", 0)
                USAGE["calls"] += 1
            text = d["choices"][0]["message"]["content"]
            m = re.search(r"(\[.*\]|\{.*\})", text, re.S)
            return json.loads(m.group(1))
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError, KeyError, AttributeError,
                TimeoutError) as e:
            if attempt == 5:
                raise RuntimeError(f"judge call failed: {type(e).__name__}")
            time.sleep(4 * (attempt + 1))


def label_pool(model, p, done):
    todo = [it for it in p["items"] if it["iid"] not in done]
    out = []
    for i in range(0, len(todo), 20):
        batch = todo[i:i + 20]
        user = (f"QUERY: {p['query']}\nCLASS (what counts as one instance): {p['hit']}\n"
                f"WINDOW: the last {p['window']}\n\nITEMS:\n"
                + "\n".join(f"{it['iid']} | {it['date'] or 'no date'} | {it['source']} | {it['title']}" for it in batch))
        got = {v["iid"]: v for v in chat(model, LABEL_SYS, user) if isinstance(v, dict) and "iid" in v}
        out += [got.get(it["iid"], {"iid": it["iid"], "on_topic": "no", "news": False, "event_key": None,
                                    "missing": True}) for it in batch]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", default="anthropic/claude-opus-5.5")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reuse", help="an earlier run whose labels are copied for the same article in the same "
                                    "query-window (same normalised title and site); only new articles are judged")
    a = ap.parse_args()
    if not KEY:
        raise SystemExit("OPENROUTER_API_KEY is not set (see .env.example)")
    jd = HERE / "runs" / a.run / "judge"
    pools = [json.loads(l) for l in open(jd / "pools.jsonl")]
    labels_f, events_f = jd / "labels.jsonl", jd / "events.jsonl"
    done = {json.loads(l)["iid"] for l in open(labels_f)} if labels_f.exists() else set()
    if a.reuse:
        import sys
        sys.path.insert(0, str(HERE))
        from pool import title_key  # noqa: E402
        rj = HERE / "runs" / a.reuse / "judge"
        old_lab = {json.loads(l)["iid"]: json.loads(l) for l in open(rj / "labels.jsonl")}
        old = {}
        for l in open(rj / "pools.jsonl"):
            p = json.loads(l)
            for it in p["items"]:
                v = old_lab.get(it["iid"])
                if v and not v.get("missing"):
                    old[(p["pid"], title_key(it["title"]), it["source"])] = v
        reused = 0
        with open(labels_f, "a") as lf:
            for p in pools:
                for it in p["items"]:
                    v = old.get((p["pid"], title_key(it["title"]), it["source"]))
                    if v and it["iid"] not in done:
                        lf.write(json.dumps({"iid": it["iid"], "on_topic": v["on_topic"], "news": v["news"],
                                             "event_key": v["event_key"], "reused_from": a.reuse}, ensure_ascii=False) + "\n")
                        done.add(it["iid"])
                        reused += 1
        print("reused labels:", reused, "of", sum(len(p["items"]) for p in pools), flush=True)
    with open(labels_f, "a") as lf, cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for res in ex.map(lambda p: label_pool(a.model, p, done), pools):
            for v in res:
                lf.write(json.dumps(v, ensure_ascii=False) + "\n")
            lf.flush()
    labels = {}
    for l in open(labels_f):
        v = json.loads(l)
        labels[v["iid"]] = v
    merged = {json.loads(l)["pid"] for l in open(events_f)} if events_f.exists() else set()

    def merge(p):
        keys = sorted({labels[it["iid"]]["event_key"] for it in p["items"]
                       if labels.get(it["iid"], {}).get("event_key")})
        if not keys:
            return {"pid": p["pid"], "groups": {}}
        groups = chat(a.model, MERGE_SYS, f"QUERY: {p['query']}\nKEYS:\n" + "\n".join(keys), max_tokens=16000)
        return {"pid": p["pid"], "groups": {k: groups.get(k, f"solo:{k}") for k in keys}}

    with open(events_f, "a") as ef, cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for res in ex.map(merge, [p for p in pools if p["pid"] not in merged]):
            ef.write(json.dumps(res, ensure_ascii=False) + "\n")
            ef.flush()
    price_in, price_out = (4e-6, 20e-6) if "opus-5.5" in a.model else (0, 0)
    usage = {**USAGE, "usd_est": round(USAGE["in"] * price_in + USAGE["out"] * price_out, 2), "model": a.model}
    with open(jd / "usage.jsonl", "a") as f:
        f.write(json.dumps(usage) + "\n")
    print("judged", len(labels), "items in", len(pools), "pools |", usage)


if __name__ == "__main__":
    main()
