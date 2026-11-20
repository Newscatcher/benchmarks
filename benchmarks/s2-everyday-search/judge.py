"""S2 judge: grades every pooled item blind (0-3), then groups story keys into distinct stories, per query-window.

Pass 1, batches of 15: grade, news, story_key (grade >= 2 news), plus story_match for one-story queries and answers
for questions. The judge sees title, site, date and the page's own description; the target story or reference
answer is given for those two query types. Pass 2, per pool: groups story keys that name the same real-world story.
Model: Claude Opus 5.5 via OpenRouter (OPENROUTER_API_KEY). Resumable. Set OPENROUTER_API_KEY, then:

    python3 judge.py --run 2026-11-18 --run 2026-11-18
"""
import argparse
import concurrent.futures as cf
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import judging as J  # noqa: E402  (chat(), USAGE, MERGE_SYS, KEY)

WIN = {"24h": "the last 24 hours", "7d": "the last 7 days"}
LABEL_SYS = """You judge news search results for a benchmark of everyday news queries. For each item (date, site, \
title, snippet) decide:
- grade: 3 = directly about the query and reports something new within the window; 2 = about the query but \
background, analysis, a roundup, opinion, or only partly about it; 1 = mentions the query's subject in passing; \
0 = unrelated or about something else.
- news: true for a news article or press release that reports something; false for listings, company or product \
pages, stock-quote pages, directories, explainers with no news, SEO pages, video pages with no text.
- story_key: only when grade >= 2 and news is true: "<main subject> | <what happened> | <key detail>", naming the \
real-world story the item reports, so items about the same story can be grouped. Otherwise null.
- For TYPE story only, story_match: true if the item reports the TARGET story, else false.
- For TYPE question only, answers: "yes" if the title or snippet states the answer (consistent with the REFERENCE \
answer), "partly" if it is about the right story but does not state the answer, "no" otherwise.
Judge only from the given fields. Do not reward an item for being popular or well known. Answer with a JSON \
array, one object per item: {"iid": ..., "grade": ..., "news": ..., "story_key": ..., "story_match": ..., \
"answers": ...} (omit story_match and answers when they do not apply)."""


def label_pool(model, p, done):
    todo = [it for it in p["items"] if it["iid"] not in done]
    out = []
    head = (f"QUERY: {p['query']}\nTYPE: {p['type']}\nWHAT COUNTS AS GOOD: {p['good']}\n"
            + (f"TARGET STORY: {p['gold']}\n" if p["type"] == "story" else "")
            + (f"REFERENCE ANSWER: {p['gold']}\n" if p["type"] == "question" else "")
            + f"WINDOW: {WIN[p['window']]}\n\nITEMS (iid | date | site | title | snippet):\n")
    for i in range(0, len(todo), 15):
        batch = todo[i:i + 15]
        user = head + "\n".join(f"{it['iid']} | {it['date'] or 'no date'} | {it['source']} | {it['title']} | "
                                f"{it['snippet'] or 'no snippet'}" for it in batch)
        got = {v["iid"]: v for v in J.chat(model, LABEL_SYS, user) if isinstance(v, dict) and "iid" in v}
        out += [got.get(it["iid"], {"iid": it["iid"], "grade": 0, "news": False, "story_key": None, "missing": True})
                for it in batch]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", default="anthropic/claude-opus-5.5")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    if not J.KEY:
        raise SystemExit("OPENROUTER_API_KEY is not set (see .env.example)")
    jd = HERE / "runs" / a.run / "judge"
    pools = [json.loads(l) for l in open(jd / "pools.jsonl")]
    labels_f, events_f = jd / "labels.jsonl", jd / "events.jsonl"
    done = {json.loads(l)["iid"] for l in open(labels_f)} if labels_f.exists() else set()
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
        keys = sorted({labels[it["iid"]]["story_key"] for it in p["items"] if labels.get(it["iid"], {}).get("story_key")})
        if not keys:
            return {"pid": p["pid"], "groups": {}}
        groups = J.chat(a.model, J.MERGE_SYS, f"QUERY: {p['query']}\nKEYS:\n" + "\n".join(keys), max_tokens=16000)
        return {"pid": p["pid"], "groups": {k: groups.get(k, f"solo:{k}") for k in keys}}

    with open(events_f, "a") as ef, cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for res in ex.map(merge, [p for p in pools if p["pid"] not in merged]):
            ef.write(json.dumps(res, ensure_ascii=False) + "\n")
            ef.flush()
    usage = {**J.USAGE, "usd_est": round(J.USAGE["in"] * 4e-6 + J.USAGE["out"] * 20e-6, 2), "model": a.model}
    with open(jd / "usage.jsonl", "a") as f:
        f.write(json.dumps(usage) + "\n")
    print("judged", len(labels), "items in", len(pools), "pools |", usage)


if __name__ == "__main__":
    main()
