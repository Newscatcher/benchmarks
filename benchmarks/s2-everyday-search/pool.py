"""S2 pooling: one blind pool per query-window from every system's top 10 (Google News top 20), keyed by normalised
title + site so an article returned by two systems is judged once.

Every cited page (all systems but Google News, whose links are redirects) is fetched once for its own publication
date and its description (og:description / meta description). The judge sees title, site, date (the page's where
found) and that description as the snippet, the same kind of snippet for every system. Page content is data only.

Writes runs/<run>/judge/pools.jsonl, runs/<run>/.key/map.json and runs/<run>/pages.json.

    python3 pool.py --run 2026-11-18
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
from pooling import site, title_key  # noqa: E402
from pages import UA, meta  # noqa: E402


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(600_000).decode("utf-8", "replace")
        t = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
        date = meta(raw, "article:published_time", "datePublished", "og:published_time", "pubdate", "date")
        if not date:
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
            date = m.group(1) if m else None
        desc = meta(raw, "og:description", "description", "twitter:description")
        return {"ok": True, "title": meta(raw, "og:title") or (html.unescape(t.group(1)).strip() if t else None),
                "date": date, "desc": re.sub(r"\s+", " ", desc)[:320] if desc else None}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def day(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    out = HERE / "runs" / a.run
    queries = {q["qid"]: q for q in json.loads((HERE / "queries.json").read_text())}
    run = json.loads((out / "run.json").read_text())
    (out / "judge").mkdir(exist_ok=True)
    (out / ".key").mkdir(exist_ok=True)
    raw = {}
    for pid in run["pids"]:
        for s in run["systems"]:
            f = out / "raw" / s / f"{pid}.json"
            if f.exists():
                raw[(pid, s)] = json.loads(f.read_text())["results"][: 20 if s == "gnews" else 10]
    urls = sorted({r["url"] for (pid, s), rs in raw.items() if s != "gnews" for r in rs if r.get("url")})
    pf = out / "pages.json"
    pages = json.loads(pf.read_text()) if pf.exists() else {}
    todo = [u for u in urls if u not in pages]
    with cf.ThreadPoolExecutor(max_workers=24) as ex:
        for u, p in zip(todo, ex.map(fetch, todo)):
            pages[u] = p
    pf.write_text(json.dumps(pages, ensure_ascii=False))
    mapping, pools = {}, []
    for pid in run["pids"]:
        qid, w = pid.split("__")
        items = {}
        for s in run["systems"]:
            for rank, r in enumerate(raw.get((pid, s), []), 1):
                k = (title_key(r["title"]), site(r["source"]))
                if not k[0]:
                    continue
                it = items.setdefault(k, {"title": r["title"], "source": site(r["source"]), "dates": [], "urls": [],
                                          "hits": []})
                it["hits"].append([s, rank])
                if r.get("date"):
                    it["dates"].append(r["date"][:10])
                if r.get("url") and s != "gnews":
                    it["urls"].append(r["url"])
        lst = list(items.values())
        random.Random(f"s2:{a.run}:{pid}").shuffle(lst)
        q = queries[qid]
        pool = {"pid": pid, "qid": qid, "window": w, "type": q["type"], "query": q["query"], "good": q["good"],
                "gold": q.get("gold"), "items": []}
        for i, it in enumerate(lst, 1):
            iid = f"{pid}#{i}"
            ps = [pages[u] for u in sorted(set(it["urls"])) if pages.get(u, {}).get("ok")]
            pdates = [d for d in (day(p.get("date")) for p in ps) if d]
            desc = next((p["desc"] for p in ps if p.get("desc")), None)
            claimed = min(it["dates"]) if it["dates"] else None
            mapping[iid] = {"hits": it["hits"], "date": claimed, "page_date": min(pdates).isoformat() if pdates else None,
                            "urls": sorted(set(it["urls"]))}
            pool["items"].append({"iid": iid, "title": it["title"], "source": it["source"],
                                  "date": mapping[iid]["page_date"] or claimed, "snippet": desc})
        pools.append(pool)
    with open(out / "judge" / "pools.jsonl", "w") as f:
        for p in pools:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    (out / ".key" / "map.json").write_text(json.dumps(mapping))
    n = sum(len(p["items"]) for p in pools)
    with_snip = sum(1 for p in pools for it in p["items"] if it["snippet"])
    print(f"{len(pools)} pools, {n} items, {with_snip} with a page snippet; {len(urls)} pages, "
          f"{sum(1 for u in urls if pages[u].get('ok'))} readable")


if __name__ == "__main__":
    main()
