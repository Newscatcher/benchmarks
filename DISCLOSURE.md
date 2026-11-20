# Disclosure

- **Conflict of interest.** NewsCatcher builds and sells the News API, one of the systems tested here (the `nc_*`
  configurations), and designed, ran and published these benchmarks.
- **Providers tested.** Listed per suite in `SYSTEMS.md` with endpoint, parameters and the documentation that
  justifies each setting. The rule is the same for every system: the best setting its own documentation recommends
  for the task, with no query hand-tuned per vendor. Variants of NewsCatcher's own configuration are disclosed as
  such.
- **Judge.** One LLM judge, Claude Opus 5.5 at temperature 0 through OpenRouter, blind to which system returned a
  result. Judge prompts are in the pipeline code. Re-judging can differ slightly.
- **Pooled recall is relative.** S1 counts the events any tested system found, so it overstates absolute recall.
- **Data we do not publish.** Exa's results (its terms restrict redistribution) and article snippets. Exa appears
  only in aggregate tables.
- **Reporting.** Each run's README states what changed since the previous run, deviations and failures, and known
  weaknesses. Published runs are never deleted or edited; corrections are added as errata.
- **Contact.** Open an issue in this repository.
