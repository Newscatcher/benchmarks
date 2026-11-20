# S2: everyday news search

**How good is the first page for the queries people and agents type most?**

The benchmark runs 60 frozen queries: a company, a person or a place, a topic, one specific story, a question, and
non-English searches. Each is run over the last 24 hours and/or the last 7 days, giving 90 query-windows. Ten
configurations from four providers each return their top 10. Every result is graded blind from 0 to 3, and each story
counts once.

This folder holds the method and the code to run the benchmark yourself. The results of each published run are in
[`results/`](results/), one folder per run date.

## Why count stories, not articles

Counted the usual way, every relevant article earns its grade. Then a first page that shows the same story five times
scores as if it held five answers. It doesn't, so the headline counts each story once, and a repeat earns nothing.
The article-level score is reported beside it.

## Run the benchmark

Run every command from this folder. The scripts use Python's standard library only (Python 3.11 or newer). Copy `.env.example` (at the repository root) to `.env`, fill in the keys
you have, and load it into your shell. A provider whose key is missing is skipped; Google News needs no key.
`queries.json` is frozen: write a new set for each new run.

```bash
python3 run.py --run 2026-11-25
```

```bash
python3 pool.py --run 2026-11-25
```

```bash
python3 judge.py --run 2026-11-25
```

```bash
python3 score.py --run 2026-11-25 > runs/2026-11-25/scores.md
```

```bash
python3 export.py --run 2026-11-25
```

What each step does:
1. **`run.py`** calls every provider for each query and window within the same seconds.
2. **`pool.py`** merges all results into blind pools. It fetches each cited page once, for its date and its own
   description. That description is the snippet the judge sees, the same kind for every vendor.
3. **`judge.py`** grades every pooled result, then groups results about the same story.
4. **`score.py`** prints the tables, with paired bootstrap intervals.
5. **`export.py`** writes the flat tables described in [DATA.md](DATA.md).

**Cost and time for one run:**
- searches: about $5.50 at list price;
- judge: about $20 for about 6,000 pooled results;
- time: about 40 minutes.

## How the scores work

- **nDCG@10 (the headline):** ranking quality from 0 to 1. Each result's gain is its grade; a result at rank r is
  divided by log2(r + 1). The ideal is the best grade of each distinct story found by any system. A repeat of a
  story already shown earns nothing.
- **nDCG@10 by article:** repeats keep their gain, and the ideal uses every result.
- **P@10:** distinct stories graded 3, divided by 10.
- **Story at rank 1 and answer at rank 1:** cover the 12 one-story queries and the 12 questions.
- **Differences between two systems** are paired over the 90 query-windows, with 95% bootstrap intervals.
- **Price:** list price at the time of the run.

[METHOD.md](METHOD.md) has the full method.

## What's in this folder

| Path | What |
|---|---|
| `results/` | one folder per published run: README with the numbers, scores, summary tables, manifest |
| `queries.json` | the 60 frozen queries: type, text, language, windows, what counts as good, plus the target story or reference answer and its source |
| `SYSTEMS.md` | every provider's endpoint, parameters and why |
| `METHOD.md` | the full method |
| `run.py`, `pool.py`, `judge.py`, `score.py`, `export.py` | the pipeline |
| `lib/` | the provider clients, pooling, judging and page-fetch helpers, shared with S1 |
| `DATA.md` | the columns of the tables `export.py` writes |

## Limitations

- **One LLM judge** (Claude Opus 5.5, temperature 0). Re-judging the same pool can differ slightly, so keep your
  labels: they make your scores exactly reproducible.
- **Some pages give no description,** so for those results the judge sees only title, site and date.
- **Small slices:** one story (12), questions (12) and non-English (6). Read those rows as indications.
- **Google News runs in US English** (`hl=en-US`), which handicaps it on non-English queries.

## Sharing a run

Exa's terms restrict redistributing its output, and article snippets and page descriptions belong to their
publishers. So only the `--public` cut of a run is ever published: it drops Exa's rows and every snippet.
Publishing is one script, `scripts/publish_run.py` at the repository root, described in
[AGENTS.md](../../AGENTS.md). Published runs live in [`results/`](results/), one folder per run date, never edited
afterwards.

## License

The code is under the MIT license (see [LICENSE](../../LICENSE) at the repository root).
