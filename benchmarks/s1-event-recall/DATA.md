# S1 data

`python3 export.py --run <run>` writes your run to `data/<run>/` as flat CSV files, one row per result, so any
aggregation can start from the rows. Add `--sqlite` for a SQLite copy.

**What `--public` leaves out,** for a cut you can share:
- **Exa's rows:** Exa's terms restrict redistributing its output. Exa appears only in `s1_summary_by_system.csv`.
- **Article snippets.**

| File | One row per |
|---|---|
| `s1_queries.csv` | query: text, group, and what counts as one instance |
| `s1_results.csv` | result: system × query-window × rank, with every judge label |
| `s1_events.csv` | distinct real event in a query-window's pool, with the first rank each published system reached it |
| `s1_metrics_per_query_window.csv` | system × query-window: every metric |
| `s1_calls.csv` | API call: status, results, latency, cost |
| `s1_summary_by_system.csv` | system: means over the scored query-windows, plus `recall_at_50_all_events` (every event found ÷ every event in all pools), latency and spend (all systems, Exa included) |
| `systems.csv` | system: vendor, endpoint, mode, settings, list price |

**Keys:**
- **`pid`** is `<qid>__<window>`: one query-window.
- **`pool_item_id`** is one judged article; systems that returned the same article share it.
- **`event_id`** is `<pid>:<group>`: one real-world event.

## `s1_results.csv`

| Column | Meaning |
|---|---|
| `system`, `rank` | who returned it, and where (1 = top) |
| `title`, `source`, `url`, `date_returned` | what the system returned |
| `judge_input_title`, `judge_input_source`, `judge_input_date` | what the judge saw |
| `page_date`, `date_used`, `date_source`, `window_start`, `in_window` | `date_source` is `page`, `system` or `none`. `in_window` is blank when there is no date; undated results count as inside. |
| `judge_on_topic` | `yes`, `partly` or `no`: is it an instance of the class? |
| `judge_news` | 1 = news, 0 = listing, profile, directory or SEO page |
| `judge_event_key`, `event_id` | the event it reports; `event_id` only on good results |
| `good` | 1 = on topic `yes`, news, and inside the window |
| `first_of_event` | 1 = the first good result about this event in this system's list: what distinct P@k counts |
| `repeat_of_event` | 1 = a good result about an event this system already showed higher up: a miss |
| `query_window_scored` | 1 = the pool held at least 10 good results, so it enters the averages |

## `s1_metrics_per_query_window.csv`

| Column | Formula |
|---|---|
| `p_at_10`, `p_at_20`, `p_at_50` | distinct good events in the top k ÷ k |
| `p_at_*_article` | good results in the top k ÷ k, repeats included |
| `recall_at_20`, `recall_at_50` | distinct good events in the top k ÷ `events_in_pool`. Averaged over query-windows, this is the headline recall; summing `events_at_50` and `events_in_pool` over query-windows first gives the all-events recall. |
| `events_at_50` | distinct good events in the top 50 |
| `repeat_share`, `non_news_share` | over the top 50 |

Parallel's top-50 metrics are blank: its public search returns at most 20 results.

## Example: distinct P@20 per system, from the rows

```python
import collections, csv
rows = [r for r in csv.DictReader(open("data/2026-11-24/s1_results.csv")) if r["query_window_scored"] == "1"]
pids = {r["pid"] for r in rows}
hits = collections.Counter(r["system"] for r in rows
                           if int(r["rank"]) <= 20 and r["good"] == "1" and r["first_of_event"] == "1")
for system, n in hits.most_common():
    print(system, round(n / 20 / len(pids), 3))
```
