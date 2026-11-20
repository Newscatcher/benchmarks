# NewsCatcher benchmarks

Open, reproducible benchmarks of news and web search APIs. Each benchmark is a suite in `benchmarks/`. Each published
run of a suite is a dated folder in that suite's `results/`.

> **Disclosure.** NewsCatcher builds and sells one of the APIs tested here and runs these benchmarks.
> See [DISCLOSURE.md](DISCLOSURE.md).

## Suites

| Suite | Question | Scale | Headline metric |
|---|---|---|---|
| [`s1-event-recall`](benchmarks/s1-event-recall/) | How many real events does one news search bring back? | 50 event classes × 3 windows (24 h, 7 d, 30 d), top 50 results, 12 configurations from 5 providers | Recall@50 per search, distinct events |
| [`s2-everyday-search`](benchmarks/s2-everyday-search/) | How good is the first page for the queries people and agents type most? | 60 frozen queries, 90 query-windows, top 10 results, 10 configurations from 4 providers | nDCG@10, counting each story once |

Each suite folder holds its method (`METHOD.md`), the exact provider settings (`SYSTEMS.md`), the frozen queries, the
pipeline and the table definitions (`DATA.md`). The pipelines use the Python standard library only.

## Published runs

| Suite | Run | Summary | Data release |
|---|---|---|---|
| | | No run has been published yet. | |

Newest first. Add a row when you publish a run; see [AGENTS.md](AGENTS.md).

## Reproduce a run

```bash
cp .env.example .env            # fill in the keys you have; a system without a key is skipped
set -a; . ./.env; set +a
cd benchmarks/s1-event-recall   # or s2-everyday-search
python3 run.py --run <run>      # then pool.py, judge.py, ... : the suite README lists the steps
```

Cost and time per run are in each suite's README. Re-judging a pool can differ slightly, so keep the labels from the
published data if you want exactly the published scores.

## What is and isn't published

Published: method, code, queries, scores, summary tables, and row-level tables in the public cut.
Not published: Exa's results, because Exa's terms restrict redistributing its output (Exa appears only in aggregate
tables), and article snippets, which belong to their publishers.

## Challenge a result

Open an issue with the run id and what you think is wrong, or a pull request with a better configuration for a
system. Corrections to a published run go in its Errata section; a changed method means a new run.

## License

Code: MIT, see [LICENSE](LICENSE).
