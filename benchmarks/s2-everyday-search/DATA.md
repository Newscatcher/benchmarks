# S2 data

`python3 export.py --run <run>` writes your run to `data/<run>/` as flat CSV files, one row per result, so any
aggregation can start from the rows. Add `--sqlite` for a SQLite copy.

**What `--public` leaves out,** for a cut you can share:
- **Exa's rows:** Exa's terms restrict redistributing its output. Exa appears only in `s2_summary_by_system.csv`.
- **Snippets and page descriptions.**

| File | One row per |
|---|---|
| `s2_queries.csv` | query: type, text, language, windows, what counts as good, target story or reference answer, source |
| `s2_results.csv` | result: system × query-window × rank, with grade, story and answer labels |
| `s2_stories.csv` | story in a query-window's pool, with its best gain and each published system's first rank. Single unkeyed items with a gain (grade 1) appear as `item:` stories. |
| `s2_metrics_per_query_window.csv` | system × query-window: every metric |
| `s2_calls.csv` | API call: status, results, latency, cost |
| `s2_summary_by_system.csv` | system: means over the 90 query-windows, latency and spend (all systems, Exa included) |
| `systems.csv` | system: vendor, endpoint, mode, settings, list price |

**Keys:**
- **`pid`** is `<qid>__<window>`: one query-window.
- **`pool_item_id`** is one judged article.
- **`story_id`** is `<pid>:<group>`: one real-world story.

## `s2_results.csv`

| Column | Meaning |
|---|---|
| `system`, `rank`, `in_top10` | who returned it and where. `in_top10` is 0 only for Google News ranks 11–20, which feed the pool, not the score. |
| `title`, `source`, `url`, `date_returned` | what the system returned |
| `judge_input_title`, `judge_input_source`, `judge_input_date` | what the judge saw (plus the page description, not published) |
| `page_date`, `date_used`, `window_start`, `in_window` | the date check |
| `judge_grade` | 0–3 |
| `judge_news` | 1 = news |
| `judge_story_key`, `story_id` | the story it reports (grade 2+, news) |
| `judge_story_match` | one-story queries: 1 = it reports the target story |
| `judge_answers` | questions: `yes`, `partly` or `no` |
| `gain` | the grade if news and inside the window, else 0 |
| `repeat_of_story` | 1 = this system already showed this story higher in its top 10 |
| `gain_counted` | 0 for a repeat, else `gain`: what the headline nDCG uses |

## `s2_metrics_per_query_window.csv`

| Column | Formula |
|---|---|
| `ndcg_at_10` | DCG of `gain_counted` ÷ the ideal DCG built from `s2_stories.csv` (headline) |
| `ndcg_at_10_article` | repeats keep their gain; the ideal uses every result |
| `p_at_10` | distinct grade-3 stories ÷ 10 |
| `found_at_1`, `found_at_10` | one-story queries |
| `answered_at_1`, `answered_at_10` | questions |
| `fresh_share`, `non_news_share`, `repeat_share` | over the top 10 |
