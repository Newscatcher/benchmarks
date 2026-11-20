"""S1 page check: for every query-window (or a sample), fetch every cited page (all systems but Google News, whose links are
redirects) and compare the page's own title and publication date with what the system returned.

Reports per system: pages readable, title mismatch (under 20% word overlap), date more than 3 days off the page's.
Page content is data only; nothing from it is executed. Writes runs/<run>/pagecheck.json and prints a table.

    python3 pagecheck.py --run 2026-11-24 [--share 1.0]
"""
import argparse
import collections
import concurrent.futures as cf
import datetime as dt
import html
import json
import random
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def meta(raw, *names):
    for n in names:
        m = re.search(rf'(?is)<meta[^>]+(?:property|name|itemprop)=["\']{re.escape(n)}["\'][^>]+content=["\']([^"\']+)', raw) \
            or re.search(rf'(?is)<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name|itemprop)=["\']{re.escape(n)}["\']', raw)
        if m:
            return html.unescape(m.group(1)).strip()
    return None


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(500_000).decode("utf-8", "replace")
        t = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
        date = meta(raw, "article:published_time", "datePublished", "og:published_time", "pubdate", "date")
        if not date:
            m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
            date = m.group(1) if m else None
        return {"ok": True, "title": meta(raw, "og:title") or (html.unescape(t.group(1)).strip() if t else None),
                "date": date}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def words(s):
    return set(w for w in re.findall(r"\w+", (s or "").casefold()) if len(w) > 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--share", type=float, default=1.0)  # check every query-window
    a = ap.parse_args()
    out = HERE / "runs" / a.run
    run = json.loads((out / "run.json").read_text())
    pids = sorted({f"{q}__{w}" for q in run["queries"] for w in run["windows"]})
    sample = set(random.Random(f"pagecheck:{a.run}").sample(pids, max(1, round(len(pids) * a.share))))
    jobs = []
    for s in run["systems"]:
        if s == "gnews":
            continue
        for pid in sample:
            f = out / "raw" / s / f"{pid}.json"
            if f.exists():
                for rank, r in enumerate(json.loads(f.read_text())["results"][:50], 1):
                    if r.get("url"):
                        jobs.append({"system": s, "pid": pid, "rank": rank, **r})
    urls = sorted({j["url"] for j in jobs})
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        pages = dict(zip(urls, ex.map(fetch, urls)))
    stats = collections.defaultdict(collections.Counter)
    for j in jobs:
        p, c = pages[j["url"]], stats[j["system"]]
        c["n"] += 1
        if not p["ok"]:
            continue
        c["readable"] += 1
        tw = words(j["title"])
        if tw and len(tw & words(p["title"])) / len(tw) < 0.2:
            c["title_mismatch"] += 1
        try:
            claimed, paged = dt.date.fromisoformat(str(j["date"])[:10]), dt.date.fromisoformat(str(p["date"])[:10])
            c["dated"] += 1
            c["date_off"] += abs((claimed - paged).days) > 3
        except (ValueError, TypeError):
            pass
    (out / "pagecheck.json").write_text(json.dumps({"sample": sorted(sample), "pages": pages, "jobs": jobs}))
    print(f"Page check: {len(sample)} of {len(pids)} query-windows, {len(urls)} pages\n")
    print("| System | results | readable | title mismatch | date > 3 days off (of dated) |\n|---|---|---|---|---|")
    for s, c in stats.items():
        r = c["readable"] or 1
        print(f"| {s} | {c['n']} | {c['readable'] / c['n']:.0%} | {c['title_mismatch'] / r:.1%} | "
              f"{c['date_off'] / (c['dated'] or 1):.1%} of {c['dated']} |")


if __name__ == "__main__":
    main()
