"""S1 runner: every query x window x system, all systems for one query-window called at the same moment.

Each system runs with the best configuration its own docs recommend for this task (see SYSTEMS.md):
NewsCatcher /search (low, medium, high; collapse=story; plus medium English-only), Exa search (auto, lite; news
category, publication-date filter, "news articles about ..."), Parallel Search v1 (advanced, basic; goal-style
objective + the query; capped at 20 results), Firecrawl search v2 (news source; and web source with the time filter),
Google News RSS (reference and recall contributor). Depth 50 (Parallel 20, Google News up to 100).
Keys from NC_KEY, EXA_KEY, PARALLEL_KEY, FIRECRAWL_KEY (see .env.example); never printed or saved. A system
whose key isn't set is skipped, so Google News alone runs with no key at all.

Writes runs/<run_id>/raw/<system>/<qid>__<window>.json (normalised results) and runs/<run_id>/calls.jsonl.

    python3 run.py --run 2026-11-24 [--queries q01,q18] [--windows 7d]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# NC search_window, days, Google News when:, Firecrawl tbs, words for objectives
WINDOWS = {"24h": ("1d", 1, "1d", "qdr:d", "24 hours"), "7d": ("7d", 7, "7d", "qdr:w", "7 days"),
           "30d": ("30d", 30, "30d", "qdr:m", "30 days")}
DEPTH = 50
KEYS = {k: os.environ.get(k, "") for k in ("NC_KEY", "EXA_KEY", "PARALLEL_KEY", "FIRECRAWL_KEY")}
UA = "curl/8.7.1"


def red(s):
    s = str(s)
    for v in KEYS.values():
        if v:
            s = s.replace(v, "<key>")
    return s


def http(method, url, headers=None, body=None, timeout=180):
    h = {"User-Agent": UA, **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    if data:
        h["Content-Type"] = "application/json"
    for attempt in range(5):
        t0 = time.time()
        try:
            req = urllib.request.Request(url, method=method, headers=h, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), time.time() - t0
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            return e.code, e.read(), time.time() - t0
        except Exception as e:
            if attempt < 4:
                time.sleep(3 * (attempt + 1))
                continue
            return None, red(f"{type(e).__name__}: {e}").encode(), time.time() - t0


def nc(effort, languages=None, collapse="story"):
    def call(q, win):
        # collapse=story: one article per story, our documented setting for the most distinct events in the top k;
        # collapse=diverse is the API default (repeats of a story rank lower), tested as a variant
        p = {"q": q, "effort": effort, "limit": DEPTH, "search_window": WINDOWS[win][0], "collapse": collapse}
        if languages:
            p["languages"] = languages
        s, b, t = http("GET", "https://api.newscatcherapi.com/news-api/search?" + urllib.parse.urlencode(p),
                       {"x-api-key": KEYS["NC_KEY"]})
        d = json.loads(b) if s == 200 else {}
        res = [{"title": r.get("title"), "url": r.get("url"), "source": (r.get("source") or {}).get("domain"),
                "date": r.get("published_at"), "snippet": r.get("snippet"), "story": (r.get("story") or {}).get("id")}
               for r in d.get("results") or []]
        cost = {"low": 0.001, "medium": 0.005, "high": 0.010}[effort] if s == 200 else 0
        return s, res, t, cost, (None if s == 200 else red(b[:300]))
    return call


def exa(kind):
    def call(q, win):
        now = dt.datetime.now(dt.timezone.utc)
        # Exa's docs: describe the pages you want; "auto" is the recommended default, "lite" the low-cost tier,
        # "deep-lite" and "deep" the research tiers (multi-step search with synthesis; added from the second run on)
        body = {"query": f"news articles about {q}", "type": kind, "category": "news", "numResults": DEPTH,
                "startPublishedDate": (now - dt.timedelta(days=WINDOWS[win][1])).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "endPublishedDate": now.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        s, b, t = http("POST", "https://api.exa.ai/search", {"x-api-key": KEYS["EXA_KEY"]}, body)
        d = json.loads(b) if s == 200 else {}
        res = [{"title": r.get("title"), "url": r.get("url"), "source": urllib.parse.urlparse(r.get("url") or "").netloc,
                "date": r.get("publishedDate"), "snippet": None, "story": None} for r in d.get("results") or []]
        return s, res, t, (d.get("costDollars") or {}).get("total") or 0, (None if s == 200 else red(b[:300]))
    return call


def gnews(q, win):
    p = {"q": f"{q} when:{WINDOWS[win][2]}", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    s, b, t = http("GET", "https://news.google.com/rss/search?" + urllib.parse.urlencode(p))
    res = []
    if s == 200:
        for item in re.findall(r"<item>(.*?)</item>", b.decode("utf-8", "replace"), re.S)[:100]:
            g = lambda tag: (re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S) or [None, ""])[1]
            src_url = (re.search(r'<source url="([^"]+)"', item) or [None, ""])[1]
            title, src = html.unescape(g("title")), html.unescape(g("source"))
            if src and title.endswith(" - " + src):
                title = title[: -len(src) - 3]
            try:
                date = dt.datetime.strptime(g("pubDate"), "%a, %d %b %Y %H:%M:%S %Z").replace(
                    tzinfo=dt.timezone.utc).isoformat()
            except ValueError:
                date = None
            res.append({"title": title, "url": html.unescape(g("link")),
                        "source": urllib.parse.urlparse(src_url).netloc, "date": date, "snippet": None, "story": None})
    return s, res, t, 0, (None if s == 200 else red(b[:300]))


def parallel(mode):
    def call(q, win):
        # Parallel's eval guide: a goal-style objective plus short keyword queries, not the raw text twice;
        # max_results and source_policy go in advanced_settings; public modes cap at 20 results
        now = dt.datetime.now(dt.timezone.utc)
        body = {"objective": f"Find news articles about {q} published in the last {WINDOWS[win][4]}. "
                             f"List as many distinct reported events as possible.",
                "search_queries": [q], "mode": mode,
                "advanced_settings": {"max_results": 20, "source_policy": {
                    "after_date": (now - dt.timedelta(days=WINDOWS[win][1])).date().isoformat()}}}
        s, b, t = http("POST", "https://api.parallel.ai/v1/search", {"x-api-key": KEYS["PARALLEL_KEY"]}, body)
        d = json.loads(b) if s == 200 else {}
        res = [{"title": r.get("title"), "url": r.get("url"), "source": urllib.parse.urlparse(r.get("url") or "").netloc,
                "date": r.get("publish_date"), "snippet": " ".join(r.get("excerpts") or [])[:400] or None,
                "story": None} for r in d.get("results") or []]
        return s, res, t, 0.005 if s == 200 else 0, (None if s == 200 else red(b[:300]))
    return call


REL = re.compile(r"(\d+)\s*(minute|hour|day|week|month|year)s?\s+ago", re.I)


def abs_date(s, now):
    """Firecrawl dates: absolute ("Nov 12, 2026", ISO) or relative ("3 days ago")."""
    if not s:
        return None
    m = REL.search(s)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {"minute": dt.timedelta(minutes=n), "hour": dt.timedelta(hours=n), "day": dt.timedelta(days=n),
                 "week": dt.timedelta(weeks=n), "month": dt.timedelta(days=30 * n), "year": dt.timedelta(days=365 * n)}
        return (now - delta[unit]).isoformat()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return dt.datetime.strptime(s.strip()[:20], fmt).replace(tzinfo=dt.timezone.utc).isoformat()
        except ValueError:
            pass
    return s


def firecrawl(source):
    def call(q, win):
        # tbs filters web results only (Firecrawl docs); the news source has no time filter, so both are run
        body = {"query": q, "sources": [source], "limit": DEPTH}
        if source == "web":
            body["tbs"] = WINDOWS[win][3]
        now = dt.datetime.now(dt.timezone.utc)
        s, b, t = http("POST", "https://api.firecrawl.dev/v2/search",
                       {"Authorization": f"Bearer {KEYS['FIRECRAWL_KEY']}"}, body)
        d = json.loads(b) if s == 200 else {}
        rows = ((d.get("data") or {}).get(source)) or []
        res = [{"title": r.get("title"), "url": r.get("url"), "source": urllib.parse.urlparse(r.get("url") or "").netloc,
                "date": abs_date(r.get("date"), now), "snippet": r.get("snippet") or r.get("description"),
                "story": None} for r in rows]
        return s, res, t, (0.0025 * 2 * max(1, -(-len(res) // 10))) if s == 200 else 0, (None if s == 200 else red(b[:300]))
    return call


SYSTEMS = {"gnews": gnews}  # no key needed
if KEYS["NC_KEY"]:
    SYSTEMS.update({"nc_low": nc("low"), "nc_medium": nc("medium"), "nc_high": nc("high"),
                    "nc_medium_en": nc("medium", "en")})  # disclosed variant: English results only
if KEYS["EXA_KEY"]:
    SYSTEMS.update({"exa_auto": exa("auto"), "exa_lite": exa("lite"), "exa_deep_lite": exa("deep-lite"),
                    "exa_deep": exa("deep")})
if KEYS["PARALLEL_KEY"]:
    SYSTEMS["parallel_advanced"] = parallel("advanced")
    SYSTEMS["parallel_basic"] = parallel("basic")
if KEYS["FIRECRAWL_KEY"]:
    SYSTEMS["firecrawl_news"] = firecrawl("news")
    # firecrawl("web") with tbs was probed on 2026-11-17 and dropped: undated general pages, not news
# variants, run only when named with --systems
VARIANTS = {"nc_medium_diverse": nc("medium", collapse="diverse"), "nc_high_diverse": nc("high", collapse="diverse"),
            "nc_high_en": nc("high", "en"), "nc_medium_diverse_en": nc("medium", "en", "diverse"),
            "nc_high_diverse_en": nc("high", "en", "diverse")}


def main():
    global SYSTEMS
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--queries")
    ap.add_argument("--windows", default=",".join(WINDOWS))
    ap.add_argument("--systems", help="comma-separated arms, e.g. nc_medium,nc_medium_diverse (default: the main set)")
    a = ap.parse_args()
    if a.systems:
        allsys = {**SYSTEMS, **VARIANTS}
        SYSTEMS = {s: allsys[s] for s in a.systems.split(",")}
    out = HERE / "runs" / a.run
    queries = json.loads((HERE / "queries.json").read_text())
    if a.queries:
        queries = [q for q in queries if q["qid"] in a.queries.split(",")]
    wins = a.windows.split(",")
    for s in SYSTEMS:
        (out / "raw" / s).mkdir(parents=True, exist_ok=True)
    log = open(out / "calls.jsonl", "a")
    (out / "run.json").write_text(json.dumps({"run": a.run, "started": dt.datetime.now(dt.timezone.utc).isoformat(),
                                              "systems": list(SYSTEMS), "windows": wins, "depth": DEPTH,
                                              "queries": [q["qid"] for q in queries]}, indent=1))
    with cf.ThreadPoolExecutor(max_workers=len(SYSTEMS)) as ex:
        for q in queries:
            for w in wins:
                todo = {s: fn for s, fn in SYSTEMS.items() if not (out / "raw" / s / f"{q['qid']}__{w}.json").exists()}
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
