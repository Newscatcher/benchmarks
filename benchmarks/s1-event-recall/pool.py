"""S1 pooling: one blind pool per query-window, from every system's results (top 50; Google News top 100).

Results are keyed by normalised title + site, so the same article from two systems is judged once. Writes
runs/<run>/judge/pools.jsonl (what the judge sees: title, source, date) and runs/<run>/.key/map.json
(item -> [(system, rank)]).

    python3 pool.py --run 2026-11-24
"""
import argparse
import json
import random
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
TWO_PART_TLDS = {"co.uk", "com.au", "co.jp", "co.in", "com.br", "co.za", "com.sg", "co.nz", "com.mx", "com.tr"}


def site(host):
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TWO_PART_TLDS:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def title_key(t):
    # keep every script (Chinese, Arabic, Hindi...): strip accents only, then any non-word run becomes one space
    t = "".join(c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c)).casefold()
    t = re.sub(r"\s[-|–—]\s[^-|–—]{2,60}$", "", t)  # trailing " - Publisher"
    return re.sub(r"[\W_]+", " ", t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    a = ap.parse_args()
    out = HERE / "runs" / a.run
    queries = {q["qid"]: q for q in json.loads((HERE / "queries.json").read_text())}
    run = json.loads((out / "run.json").read_text())
    (out / "judge").mkdir(exist_ok=True)
    (out / ".key").mkdir(exist_ok=True)
    mapping, pools = {}, []
    for qid in run["queries"]:
        for w in run["windows"]:
            items = {}
            for s in run["systems"]:
                f = out / "raw" / s / f"{qid}__{w}.json"
                if not f.exists():
                    continue
                depth = 100 if s == "gnews" else 50
                for rank, r in enumerate(json.loads(f.read_text())["results"][:depth], 1):
                    k = (title_key(r["title"]), site(r["source"]))
                    if not k[0]:
                        continue
                    it = items.setdefault(k, {"title": r["title"], "source": site(r["source"]), "dates": [],
                                              "urls": [], "hits": []})
                    it["hits"].append([s, rank])
                    if r.get("date"):
                        it["dates"].append(r["date"][:10])
                    if r.get("url") and s != "gnews":
                        it["urls"].append(r["url"])
            lst = list(items.values())
            random.Random(f"s1:{a.run}:{qid}:{w}").shuffle(lst)
            pool = {"pid": f"{qid}__{w}", "qid": qid, "window": w, "query": queries[qid]["query"],
                    "hit": queries[qid]["hit"], "items": []}
            for i, it in enumerate(lst, 1):
                iid = f"{qid}__{w}#{i}"
                date = min(it["dates"]) if it["dates"] else None
                mapping[iid] = {"hits": it["hits"], "date": date, "urls": sorted(set(it["urls"]))}
                pool["items"].append({"iid": iid, "title": it["title"], "source": it["source"], "date": date})
            pools.append(pool)
    with open(out / "judge" / "pools.jsonl", "w") as f:
        for p in pools:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    (out / ".key" / "map.json").write_text(json.dumps(mapping))
    print(len(pools), "pools,", sum(len(p["items"]) for p in pools), "items")


if __name__ == "__main__":
    main()
