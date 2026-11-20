# S1: news search event recall

**How many real events does one news search bring back?**

The benchmark searches 50 event classes over the last 24 hours, 7 days and 30 days. Examples: "seed rounds", "CEO
changes in fintech", "product recalls", "ransomware attacks on hospitals". Twelve configurations from five providers each
return their top 50 results. Every result is judged blind, and each real-world event counts once.

This folder holds the method and the code to run the benchmark yourself. The results of each published run are in
[`results/`](results/), one folder per run date.

## Why recall

A buyer watching a class of events wants every instance, not one good article. A deal team wants every seed round in
climate tech; a risk team wants every recall and every breach.
- Benchmarks built on questions with one known answer now put every serious provider at 90% or more.
- This one measures what such a buyer gets from one search:
  - of all the qualifying events any system found, how many are in this system's results;
  - how much of the list is right;
  - what it costs per distinct event.

## Run the benchmark

Run every command from this folder. The scripts use Python's standard library only (Python 3.11 or newer). Copy `.env.example` (at the repository root) to `.env`, fill in the keys
you have, and load it into your shell. A provider whose key is missing is skipped; Google News needs no key.

```bash
python3 run.py --run 2026-11-24
```

```bash
python3 pool.py --run 2026-11-24
```

```bash
python3 judge.py --run 2026-11-24
```

```bash
python3 pagecheck.py --run 2026-11-24
```

```bash
python3 score.py --run 2026-11-24 > runs/2026-11-24/scores.md
```

```bash
python3 export.py --run 2026-11-24
```

What each step does:
1. **`run.py`** calls every provider for each query and window within the same seconds and saves the raw results.
2. **`pool.py`** merges all results into one shuffled pool per query-window, with system names hidden.
3. **`judge.py`** labels every pooled result, then groups results about the same event.
4. **`pagecheck.py`** fetches every cited page to read its real publication date.
5. **`score.py`** prints the tables, with paired bootstrap intervals.
6. **`export.py`** writes the flat tables described in [DATA.md](DATA.md).

Every step is resumable: a rerun skips calls and judgments already on disk.

**Cost and time for one run** (50 queries × 3 windows, every provider):
- searches: about $24 at list price;
- judge: about $75 for about 38,000 pooled results;
- time: about two hours, mostly the judge.

## How the scores work

Each distinct event counts once; a second article about the same event counts as a miss. A query-window enters the
averages when its pool holds at least 10 good results.
- **Precision P@k:** distinct qualifying events in the top k, divided by k.
- **Recall@50, per search (the headline):** distinct qualifying events in the top 50, divided by all distinct
  qualifying events any system found for that query-window. That pool is every system's top 50 plus Google News's
  top 100. The shares are then averaged, so every query-window counts the same.
- **Recall@50, all events:** every event from every query-window goes into one pool, and each system's events found
  are divided by the total. Broad searches with many events weigh more.
- **Repeats and non-news:** shares of the top 50.
- **Differences between two systems** are paired over query-windows, with 95% bootstrap intervals. An interval that
  crosses zero is a tie.
- **Price:** list price at the time of the run.

[METHOD.md](METHOD.md) has the full method.

## What's in this folder

| Path | What |
|---|---|
| `results/` | one folder per published run: README with the numbers, scores, summary tables, manifest |
| `queries.json` | the 50 event classes: the query text, its group, and what counts as one instance |
| `SYSTEMS.md` | every provider's endpoint, parameters and why, from its own documentation |
| `METHOD.md` | the full method: pooling, judging, dates, metrics, statistics, limitations |
| `run.py`, `pool.py`, `judge.py`, `pagecheck.py`, `score.py`, `export.py` | the pipeline |
| `DATA.md` | the columns of the tables `export.py` writes |

## Limitations

- **Pooled recall is relative.** It counts the events any tested system found, so it overstates absolute recall.
  System rankings under pooling are known to be stable (Zobel, SIGIR 1998).
- **One LLM judge** (Claude Opus 5.5, temperature 0). Re-judging the same pool can differ slightly, so keep your
  labels: they make your scores exactly reproducible.
- **S1's judge sees title, site and date only,** not the article text.
- **Parallel's public search returns at most 20 results,** so it has no top-50 numbers.
- **Firecrawl's news search has no time filter,** so out-of-window results count as misses.

## Sharing a run

Exa's terms restrict redistributing its output, and article snippets and page descriptions belong to their
publishers. So only the `--public` cut of a run is ever published: it drops Exa's rows and every snippet.
Publishing is one script, `scripts/publish_run.py` at the repository root, described in
[AGENTS.md](../../AGENTS.md). Published runs live in [`results/`](results/), one folder per run date, never edited
afterwards.

## License

The code is under the MIT license (see [LICENSE](../../LICENSE) at the repository root).
