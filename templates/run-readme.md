# {{suite}} · run {{run}}

> Published run. This folder is immutable: corrections go in the Errata section below.
> Method: [METHOD.md](../../METHOD.md) · Systems and settings: [SYSTEMS.md](../../SYSTEMS.md) ·
> Table columns: [DATA.md](../../DATA.md) · Disclosure: [DISCLOSURE.md](../../../../DISCLOSURE.md)

| | |
|---|---|
| Run id | `{{run}}` |
| Harness commit | `{{harness_commit}}` |
| `queries.json` SHA-256 | `{{queries_sha256}}` |
| Release | [`{{tag}}`](https://github.com/Newscatcher/benchmarks/releases/tag/{{tag}}) |
| Row-level data | `{{zip_name}}` (SHA-256 `{{zip_sha256}}`) |
| Judge | TODO: model, prompt version, temperature |
| Run dates | TODO: first and last API call, UTC |

## Results

Copied from `scores.md`, as produced by `score.py`. Do not retype numbers.

{{scores}}

## What changed since the previous run

TODO: list every difference that affects comparability (queries, systems and settings, judge model or prompt,
windows, depth). Write "First published run." if there is no previous run.

## Deviations and failures

TODO: provider outages, timeouts, skipped systems, partial results, and how `score.py` treated them.

## Known weaknesses

TODO: anything in this run that favours or hurts a system, including NewsCatcher's own results.

## Data

Small tables are in this folder. Row-level tables are in the Release zip above. Both are the public cut: no Exa rows
(Exa appears only in aggregate files) and no snippets. Verify a download:

```bash
shasum -a 256 {{zip_name}}
```

## Errata

None.
