# S1 method

## The question

*I watch a class of events. When I search for it over the last day, week or month, how many of the real events does
one search bring back, and how much of what comes back is right?*

That's how news search is used for lead lists, market maps, and deal and risk monitoring. It rewards recall: one
perfect top result isn't enough.

## Queries

- **50 event classes** in `queries.json`, written for the benchmark before any system was called.
- **Groups:** Funding (10), M&A (7), Leadership (7), Risk (6), Workforce (5), Expansion (4), Regulation (4), Launches
  (3), Partnerships (2), Legal (1) and Capital markets (1).
- **Each class defines one instance** (`hit`). For "seed rounds" that's "a startup's seed round (company + round)".
- **Plain query text,** as a user would type it. Where a vendor's documentation asks for a different query shape,
  one fixed template is applied to all 50 queries (see [SYSTEMS.md](SYSTEMS.md)).
- **No query is tuned to any vendor.**

## Windows and depth

- **Windows:** each class runs over the last 24 hours, 7 days and 30 days, so 150 query-windows.
- **Depth:**
  - every system asks for 50 results;
  - Parallel's public search returns at most 20;
  - Google News RSS returns up to 100, which feed the recall pool but aren't scored beyond 50.
- **Timing:** all systems for a query-window are called within the same seconds, so none sees fresher news.

## Systems

Each provider runs in the setting its own documentation recommends for this task. Every setting is a documented public
option, and each one was checked with a live call before the run. Details are in [SYSTEMS.md](SYSTEMS.md).
- **NewsCatcher News API `/search`:** effort `low`, `medium` (the default) and `high`, all with `collapse=story`, plus
  `medium` with English results only.
- **Exa `/search`:** `auto` (the default) and `lite`, plus `deep-lite` and `deep` from the second run on, with the
  news category and publication-date filters.
- **Parallel Search:** `advanced` and `basic`.
- **Firecrawl search,** news source.
- **Google News RSS,** as a reference.

## Pooling

- **Merging:** every result is keyed by its normalised title and site, so the same article from several systems is
  judged once.
- **Pool:** per query-window, a shuffled list with system names hidden.

## Judging

- **Model:** Claude Opus 5.5 via OpenRouter, at temperature 0, in batches of 20. The exact prompts are in `judge.py`.
- **What the judge sees:** each result's title, site and date.
- **Labels:**
  - **on_topic:** `yes` if the item reports one instance of the class; `partly` if it's related but not a clear
    instance (analysis, roundup, rumour, wrong sector or region); `no` otherwise.
  - **news:** true for a news article or press release that reports something; false for listings, directories,
    company pages, stock-quote pages, explainers and SEO pages.
  - **event_key:** for on-topic news only, written as `organisation | event | key detail`.
- **Grouping:** a second pass groups event keys that name the same real-world event.

## Dates

- **Page check:** `pagecheck.py` fetches every cited page and reads its own publication date.
- **Window membership:** a result is inside the window if its date is no earlier than the call date minus the window,
  minus one day of slack. The page's date is used where found; otherwise the system's.
- **Reported per system:** the share of dates more than 3 days off the page.

## Scoring

- **A good result** is on topic (`yes`), news, and inside the window.
- **P@10, P@20 and P@50:** distinct good events in the top k, divided by k.
  - Only the first good result about each event counts; later results about the same event are misses.
  - Missing slots also count as misses.
- **P@k by article** (repeats counted) is reported as a secondary column.
- **Recall@20 and recall@50:** distinct good events in the top k, divided by all distinct good events in the
  query-window's pool, then averaged over query-windows (macro). This is the headline: a narrow class counts as
  much as a broad one.
- **Recall@50 over all events (micro):** the sum of every system's distinct good events in the top 50, divided by
  the sum of all pools' events. Broad classes weigh more. It's reported beside the headline because the two can rank
  systems differently: one system can be stronger on narrow classes and another on broad ones.
- **Also reported:** distinct events in the top 50; the shares of the top 50 that are repeats and non-news; median
  and p90 latency; and list price per search and per 1,000 distinct events.
- **Scored query-windows:** those whose pool holds at least 10 good results.

## Statistics

- Every difference between two systems is paired over query-windows.
- It carries a bootstrap 95% interval: 10,000 resamples, seed 7.
- An interval that crosses zero is reported as a tie.

## Limitations

- **Pooled recall overstates absolute recall:** events no system found are invisible. Relative rankings under pooling
  are stable (Zobel 1998, *How reliable are the results of large-scale information retrieval experiments?*).
- **One judge model.** A human audit of 200 labels is pending; the target is at least 90% agreement.
- **The judge sees titles only,** so it can misjudge a vague headline.
