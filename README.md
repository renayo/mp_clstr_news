# mp_clstr_news — minor-planet names in the news, second study

A pre-registered, five-year test of whether news coverage of minor-planet namesakes
carries structure at the classical astrological aspects to thirteen solar-system
reference points, and whether the qualities of that coverage follow the qualities
tradition assigns to the planets and signs involved.

**Read [`PREREGISTRATION.md`](PREREGISTRATION.md) first.** It is the study. Everything
in this repository exists to carry it out exactly as written. News data come from
[CLSTR](https://clstr.news) through its v1 API; ephemerides from JPL Horizons.

## Layout

```
PREREGISTRATION.md      the registered design (versioned; frozen text is never edited)
config/study.yaml       every registered parameter, machine-readable
config/rubric.yaml      the classification rubric — the exact text the classifier sees
data/body_names.csv     1,211 names with the verified flag (1,122 in the analysis set)
data/unnamed_pool.txt   1,211 numbered, unnamed main-belt asteroids (the control pool)
data/search_cohorts.csv the five search cohorts (seeded)
data/body_ids.csv       name → minor-planet number → SPK-ID          (built at freeze)
data/ephemeris/         daily longitudes for the whole window         (built at freeze)
mpclstr/                the pipeline (see below)
tests/                  pytest suite (mocked API, synthetic data, planted signals)
raw/                    verbatim API responses, one JSONL file per layer and day
manifests/              daily SHA-256 manifests, hash-chained
derived/                outcome tables regenerated from raw/ by mpclstr.derive
classified/             per-cluster label probabilities
results/                summary JSON and null draws of each analysis run
.github/workflows/      daily collector and the test workflow
```

## Pipeline

| Step | Command | Registered section |
|---|---|---|
| Resolve names to numbers | `python -m mpclstr.ephemeris resolve` | §6 |
| Build the ephemeris | `python -m mpclstr.ephemeris build` | §6 |
| Make the search cohorts | `python -m mpclstr.cohorts` | §4.4 |
| Collect one day | `CLSTR_API_KEY=… python -m mpclstr.collect --date 2026-09-16` | §4.2–4.4, §4.7 |
| Derive outcome tables | `python -m mpclstr.derive` | §4.6 |
| Classify matched clusters | `python -m mpclstr.classify --backend llm --model … --revision …` | §5 |
| Re-derive with qualities | `python -m mpclstr.derive` | Appendix D |
| Confirmatory run | `python -m mpclstr.analysis` | §7 |
| Robustness variants | `python -m mpclstr.analysis --node true`, `--sidereal`, `--series A`, `--exclude-short`, `--exclude-top 12`, `--septile-lag 52`, `--year 2027`, `--series N_union`, `--ephemeris data/ephemeris_noon` | §7.7 |

Every command works from any directory; paths resolve from the repository root.
`python -m mpclstr.collect --mock` runs the whole collector against a synthetic API
without a key or network, and `python -m mpclstr.synthetic --root /tmp/s --plant 0.3`
followed by `python -m mpclstr.analysis --root /tmp/s --n-rep 200` runs the analysis
on synthetic data with a planted Sun-aspect signal.

The confirmatory analysis at full scale (1,826 days × 1,122 bodies × 1,211-body pool,
5,000 replicates per null) needs about 4 GB of memory and roughly an hour.

## Running the daily collector

The collector must run once a day at the registered time (12:00 UTC) with the API
key in the environment variable `CLSTR_API_KEY`. Two options:

**GitHub Actions (recommended).** `.github/workflows/collect.yml` runs the collector at
12:00 UTC, commits the day's manifest, derived tables and matched-cluster metadata, keeps
the day's raw responses as a workflow artifact, and syncs them to object storage when
the `RAW_S3_BUCKET` secret is set. Add the key under *Settings → Secrets and variables →
Actions* as `CLSTR_API_KEY`. Scheduled workflows can start several minutes late under
load; the request timestamps in `raw/` are the record of when each call was made.

**A local machine.** A `launchd` job (macOS) or `cron` entry that runs
`python -m mpclstr.collect && python -m mpclstr.derive && git add -A && git commit -m "collect $(date -u +%F)" && git push`
at 12:00 UTC does the same. Keep `CLSTR_API_KEY` in the job's environment, never in a
file inside the repository.

## Data handling

Raw responses are archived verbatim under `raw/` (about 50 MB a day). They are not
committed: the workflow keeps each day's raw files as a workflow artifact and, when the
`RAW_S3_BUCKET` secret is set, syncs them to S3-compatible object storage; monthly, the
archive is deposited on Zenodo as a checksummed record referenced from `manifests/`
(§4.7). The repository commits the manifests (SHA-256 of every raw file, hash-chained),
the derived tables, and the metadata of matched clusters. The text of matched clusters is
written to `classified/clusters_text.csv`, git-ignored until CLSTR's written permission to
publish it is on file (§11).

## Install

```
pip install -r requirements.txt          # numpy, pandas, scipy, pyyaml, requests, pytest
pip install torch transformers           # only for the classifier backends
pytest -q
```

## Provenance

Predecessor studies: [minor_planets_2026](https://github.com/renayo/minor_planets_2026)
(Oshop & Coops, 2026) and the [FPOA–Libra audit](https://github.com/renayo/FPOA_Minor_Planets_2026).
The unnamed pool, the L2 normalisation, the binned wave, the circular autocorrelation
estimator, the compound and unnamed nulls, and the Meeus mean-node Rahu are carried over
from them unchanged. News data: CLSTR (https://clstr.news). Ephemerides: JPL Horizons.
Licence: MIT.
