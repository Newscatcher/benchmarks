# S1 system configurations (2026-11-17)

**Rule:** every system runs with the best setting its own documentation recommends for this task: news about an
event class over the last 24 h, 7 d or 30 d, as many distinct events as possible in one call. Every setting is a
documented public option; no query is hand-tuned per vendor.
- **Templates:** where a vendor's docs ask for a different query shape, one fixed template is applied to all 50
  queries.
- **Check:** each configuration was tested with one live call ("seed rounds", 7 d) on 2026-11-17.

| Arm | Endpoint and parameters | Why (vendor docs) |
|---|---|---|
| **nc_medium** (headline) | `GET /news-api/search` · `q` = the query · `effort=medium` · `collapse=story` · `limit=50` · `search_window` 1d/7d/30d · default `content_type=news` | `collapse=story` gives one article per story, the most distinct events per slot; medium is the default and recommended for plain-word queries |
| nc_low, nc_high | same, `effort=low` / `high` | the other two effort levels; high merges same-event stories |
| nc_medium_en | same as nc_medium, `languages=en` | disclosed variant: English results only |
| **exa_auto** | `POST /search` · `query` = "news articles about {query}" · `type=auto` · `category=news` · `numResults=50` · `startPublishedDate`/`endPublishedDate` = the window | `auto` is Exa's recommended default ("instant" and "fast" are now legacy); its docs say to describe the pages you want and to use publication-date filters for a time window |
| exa_lite | same, `type=lite` | Exa's low-cost, low-latency tier |
| exa_deep_lite | same, `type=deep-lite` (from the second run on) | Exa's lightweight research tier: multi-step search with synthesis; the docs give it a steady latency of about 4 s |
| exa_deep | same, `type=deep` (from the second run on) | Exa's full research tier, which replaced `deep-reasoning`; we score its result list, not its synthesis |
| **parallel_advanced** | `POST /v1/search` · `objective` = "Find news articles about {query} published in the last {window}. List as many distinct reported events as possible." · `search_queries` = [query] · `mode=advanced` · `advanced_settings.max_results=20` · `source_policy.after_date` = window start | Parallel's eval guide: a goal-style objective plus short keyword queries (not the raw text twice); advanced is its highest-quality mode; public search caps at 20 results |
| parallel_basic | same, `mode=basic` | Parallel's recommended starting point for evals |
| **firecrawl_news** | `POST /v2/search` · `query` = the query · `sources=["news"]` · `limit=50` | Firecrawl's news source. Its time filter (`tbs`) applies to web results only, so the window is enforced at scoring: out-of-window stories count as misses |
| gnews (reference) | RSS `q` = "{query} when:1d/7d/30d" · `hl=en-US` | the consumer reference and a recall contributor; not priced |

**Probed and dropped:**
- **Firecrawl web with `tbs`:** it returned undated general pages ("What is seed funding?"), not news.
- **Exa instant and fast:** legacy per Exa's spec, replaced by `lite`.

**Depth limits, disclosed on the page:**
- **Parallel caps at 20.** It's compared on P@10, P@20 and recall@20, not on P@50.
- **Google News's depth (up to 100)** only feeds the recall pool.
- **Exa deep-lite and deep return a short list,** not the 50 asked for. Exa documents no cap, so they're scored
  like every other system: empty slots count as misses.

**Per run** (50 queries × 3 windows = 150 query-windows):

| Line | Cost |
|---|---|
| NewsCatcher (4 arms) | about 3,150 NCC (≈$3) |
| Exa (4 arms; deep-lite and deep about $5.50 of it) | about $20 |
| Parallel (2 arms) | about $1.50 |
| Firecrawl | about $3.75 |
| Judge (about 40k pooled results) | about $75 |
| **Total** | **about $100 per run** |
