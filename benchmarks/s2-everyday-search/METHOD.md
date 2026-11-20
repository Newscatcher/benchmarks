# S2 method

## The question

*For an ordinary query (a company, a topic, a story, a question), how good is the first page?*

S2 complements [S1](https://github.com/Newscatcher/benchmark-s1-event-recall), which measures recall on event classes.
S2 measures the top 10.

## Queries

**60 queries, frozen before any system was called:** 2026-11-18 15:57 CET. The sha256 of `queries.json` is
`50a32c524e82fe87a690b950eee15efae031a6f6010bdc1ece90ee093b1cb6b9`.

| Type | Count | Example | Windows | What counts as good |
|---|---|---|---|---|
| Company, person or place (`entity`) | 15 | "Nvidia", "UniCredit" | 24 h and 7 d | mainly about the entity, reporting something new in the window |
| Topic | 15 | "AI regulation", "Gaza ceasefire" | 24 h and 7 d | mainly about the topic, reporting a new development |
| One story | 12 | "Prague train collision" | 7 d | reports that story |
| Question | 12 | "Why did Italy fine Meta?" | 7 d | its title or snippet states the answer |
| Non-English | 6 | "日銀 金融政策", "Banco Central taxa de juros" | 7 d | as for entity and topic, in that language |

- **Entity and topic queries** follow the shapes people use in a news search app. They were written fresh: no
  customer's query is used.
- **One-story queries** were sampled from Wikipedia's Portal:Current events for Nov 12–18, 2026.
- **Questions** were written from those stories. Each has a reference answer and a source in `queries.json`.
- **Boolean queries are left out,** because not every API supports them.

## Systems

The same systems and settings as S1 ([SYSTEMS.md](SYSTEMS.md)), with 10 results per call:
- NewsCatcher `low`, `medium` and `high` (`collapse=story`);
- Exa `auto` and `lite`, plus `deep-lite` and `deep` from the second run on;
- Parallel `advanced` and `basic`;
- Firecrawl news, which was configured but failed on credits, so it isn't scored;
- Google News RSS, with its top 20 pooled as a reference.

All systems for a query-window are called within the same seconds.

## Pooling

- **Merging:** each system's top 10 (Google News: top 20) is keyed by normalised title and site, so the same article
  from two systems is judged once.
- **Page fetch:** every cited page (all systems but Google News, whose links are redirects) is fetched once. It gives
  the page's own publication date and its description (og:description or meta description, cut to 320 characters).
  That description is the snippet the judge sees: the same kind of snippet for every vendor.

## Judging

- **Model:** Claude Opus 5.5 via OpenRouter, at temperature 0, in batches of 15. The exact prompts are in `judge.py`.
- **What the judge sees:** the query, its type, what counts as good, the target story or reference answer where
  there is one, and the window. For each result: date, site, title and snippet.
- **Labels:**
  - **grade:** 3 = directly about the query and new in the window; 2 = about it but background, analysis, a roundup
    or opinion; 1 = a passing mention; 0 = unrelated.
  - **news:** true for a news article or press release that reports something.
  - **story_key:** for grade 2+ news only.
  - **story_match:** for one-story queries.
  - **answers:** for questions: `yes`, `partly` or `no`.
- **Grouping:** a second pass groups story keys that name the same real-world story.

## Scoring

- **Gain:** a result's grade, if it's news and dated inside the window (the page's date where found; one day of
  slack), else 0.
- **Repeats:** a later result about a story already shown in the same system's top 10 gains 0.
- **nDCG@10:** DCG = Σ (2^gain − 1) / log2(rank + 1). The ideal ranking takes the best grade of each distinct story
  in the pool, sorted, top 10.
- **nDCG@10 by article:** repeats keep their gain, and the ideal uses every result's grade.
- **P@10:** distinct stories graded 3 in the top 10, divided by 10.
- **Story found and question answered:** at rank 1 and anywhere in the top 10. A target story counts when the item
  matches it and is inside the window; a question counts when the item states the answer.
- **Also reported:** freshness (dated top-10 results inside the window), non-news share, repeat share, median and
  p90 latency, and list price.

## Statistics

- Every difference between two systems is paired over the 90 query-windows.
- It carries a bootstrap 95% interval: 10,000 resamples, seed 7.

## Limitations

- **One judge model.** A human audit of 150 labels is pending.
- **Some pages give no description,** so for those results the judge sees only title, site and date.
- **Small slices** for single-story queries, questions and non-English queries.
