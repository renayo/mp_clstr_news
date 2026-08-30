# Pre-Registration Declaration

## Minor-Planet Namesakes in a Clustered News Index and Their Angular Relations to Thirteen Solar-System Reference Points (Second Study)

| | |
|---|---|
| **Repository** | https://github.com/renayo/mp_clstr_news |
| **Document** | `PREREGISTRATION.md`, version 0.3 (draft for freeze) |
| **Date of this version** | 2026-08-30 |
| **Status** | Draft. To be frozen as version 1.0 before the first confirmatory observation. The frozen text is never edited in place; every later change is dated in the changelog (§13). |
| **Principal investigator** | Renay Oshop |
| **Predecessor studies** | Oshop & Coops (2026), *In daily news, minor planet names show up in accordance with harmonic patterning* — https://github.com/renayo/minor_planets_2026; and the single-axis audit of the FPOA–Libra axis — https://github.com/renayo/FPOA_Minor_Planets_2026, https://fpoa.netlify.app |

---

## 0. Declaration of intent

We declare, in advance of collecting any confirmatory data, the hypotheses, the population of bodies, the data source and acquisition procedure, the ephemeris and angle conventions, the classification of news content, the test statistics, the null models, the inference thresholds, the exclusion rules, the study window, and the schedule of analyses for the second study of minor-planet namesakes in the news. This document is committed to a public repository and time-stamped by independent means (§10) so that the record of what was intended precedes the record of what was found. Any departure from this plan will be reported as such.

The question is the one asked by the first study, put to a documented and versioned news index over a window more than six times longer, with the content of the news classified along five axes fixed in advance: when a named minor planet stands at one of the classical aspect angles to a solar-system reference point, is there measurable structure in how often its namesake appears in significant news; does that structure differ between the aspects tradition calls harmonious and those it calls challenging; and do the qualities of the coverage — its polarity, its element, the gender of its subjects, its yin or yang character, and its modality — follow the qualities tradition assigns to the planets and signs involved?

---

## 1. Background

The first study tracked the proper names of 1,121 officially designated minor planets across Google News for 290 consecutive days in 2022 and asked whether the angular separations between those bodies and twelve reference points showed statistical structure at the harmonic angles treated as salient in astrological tradition. It reported joint autocorrelation at the aspect separations at several times its chance expectation under two null models, with the Moon serving as an internal negative control. A subsequent audit (the FPOA–Libra study) showed that the aspect-lag autocorrelations of that first edition were re-descriptions of a single low-order cosine whose axis fell within a few degrees of the equinoctial axis, and it tested that axis directly with one pre-specified statistic.

Both predecessors were retrospective in the sense that the analysis plan was written after the counts existed, both depended on a keyword index (Google News result counts) whose definition was never documented and could change without notice, and neither could say anything about what kind of news the counts contained. The present study is designed to remove those weaknesses.

---

## 2. Hypotheses

Hypotheses H1 through H8 are confirmatory. Everything in §7.8 is exploratory and is labelled as such wherever it is reported.

### Block I — Aspect structure

**H1 — Aspect concentration (omnibus).** Pooled across the twelve independent reference points, the news presence of the named bodies, expressed as a function of each body's angular separation from the reference point, is concentrated at the nine pre-specified aspect angles. Statistic: the directional harmonic V-statistic summed over aspect harmonics and reference points (§7.3, *D*). Prediction: *D* > 0, exceeding both null distributions at the one-sided 0.05 level.

**H2 — Aspect concentration (per reference point).** For each of the twelve independent reference points, *D_R* exceeds both null distributions at the Bonferroni-corrected one-sided level 0.05/12.

**H3 — Replication of the FPOA–Libra axis.** For the FPOA reference point, the fixed-direction projection *T* = Σ_L *w*(L)·cos(L − 180°), the statistic of the FPOA audit, is positive and exceeds both null distributions at the one-sided 0.05 level. This is an out-of-sample replication with a new index and a new window; the direction is fixed here in advance.

### Block II — Qualities of coverage

Each hypothesis in this block is one pre-specified statistic built from the classified coverage (§5) and the harmonic machinery of §7.3. The five are tested as a family at Bonferroni-corrected α = 0.05/5 = 0.01 each, one-sided, against both nulls.

**H4 — Polarity and aspect class.** Positively valenced presence, relative to negatively valenced presence, is more concentrated at the harmonious aspects (30°, 60°, 72°, 120°) than at the challenging aspects (45°, 90°, 180°). Statistic Δ_pol (§7.5). Prediction: Δ_pol > 0.

**H5 — Element and planetary tattva.** Coverage carrying a classical planet's own element (Jupiter–space, Saturn–air, Sun and Mars–fire, Moon and Venus–water, Mercury–earth) is more concentrated at aspects to that planet than coverage carrying the other four elements. Statistic *G*_elem (§7.5). Prediction: *G*_elem > 0.

**H6 — Gender and planetary gender.** Coverage whose principal subject is male is more concentrated at aspects to the male planets (Sun, Mars, Jupiter) than coverage whose principal subject is female, and the reverse holds for the female planets (Moon, Venus). Statistic *G*_gen (§7.5). Prediction: *G*_gen > 0.

**H7 — Yin, yang, and sign polarity.** Yang-classified presence, relative to yin-classified presence, is concentrated in the yang (odd) tropical signs occupied by the named body. Statistic *Y* (§7.6), the sixth-harmonic projection at the yang sign centres. Prediction: *Y* > 0.

**H8 — Modality and sign modality.** Cardinal-, fixed-, and mutable-classified presence are each concentrated in the cardinal, fixed, and mutable tropical signs respectively. Statistic *M* (§7.6), the sum of the three fourth-harmonic projections at their own sign centres. Prediction: *M* > 0.

A "harmonic patterning" family — the circular autocorrelation at aspect lags used by the first study — is retained as the replication statistic for the earlier methodology (§7.4) and is reported alongside H1 and H2; the confirmatory claims of Block I rest on *D*.

---

## 3. Population

### 3.1 Named bodies

The tracked names are the 1,211 names in `data/body_names.csv`, the list searched in the first study. The 1,122 names marked `verified = 1` constitute the analysis set. The 89 names marked `verified = 0` are those whose orbital geometry could not be verified against JPL Horizons across the first study's window; they are excluded in advance and will not be added back regardless of how their namesakes fare in the news. No name is excluded for any other reason at the confirmatory level; pre-specified sensitivity exclusions are listed in §7.7.

### 3.2 Reference points

Thirteen reference points are evaluated: the First Point of Aries (FPOA, 0° tropical longitude by definition), the Sun, the Moon, Mercury, Venus, Mars, Jupiter, Saturn, Uranus, Neptune, Pluto, Rahu (the mean north lunar node), and Ketu (the mean south lunar node, Rahu + 180°).

Ketu is a distinct point in the tradition under test but is not statistically independent of Rahu. Because every separation from Ketu equals the separation from Rahu plus 180°, the circular autocorrelation of the Ketu wave is identical to that of the Rahu wave at every lag, and the harmonic V-statistics satisfy *V_n*(Ketu) = (−1)^*n*·*V_n*(Rahu) — identical for the even harmonics (opposition, square, sextile, octile, semisextile) and sign-reversed for the odd ones (conjunction, trine, quintile, septile). Ketu's results are reported in full but are derived, and every multiplicity correction counts twelve independent reference points.

The classical attributes used by Block II follow Bṛhat Parāśara Horā Śāstra and are fixed here: element (tattva) — Sun fire, Moon water, Mercury earth, Venus water, Mars fire, Jupiter space, Saturn air; gender — Sun, Mars, Jupiter male; Moon, Venus female; Mercury, Saturn neuter (excluded from H6); benefic — Jupiter, Venus; malefic — Saturn, Mars (the first study's grouping, used in exploratory contrasts). The outer planets, the nodes, and FPOA carry no classical tattva or gender and enter Block II only in exploratory analyses; where a convention is needed for those analyses, Rahu is treated like Saturn (air) and Ketu like Mars (fire), following the dictum *śanivad rāhuḥ kujavat ketuḥ*.

### 3.3 Aspects

| Aspect | Angle | Harmonic *n* | ACF lag (°) | Class (H4) |
|---|---|---|---|---|
| Conjunction | 0° | 1 | — (lag 0 is identically 1) | unclassified |
| Semisextile | 30° | 12 | 30 | harmonious |
| Octile (semisquare) | 45° | 8 | 45 | challenging |
| Septile | 51.43° (360/7) | 7 | 51 (52 as sensitivity) | unclassified |
| Sextile | 60° | 6 | 60 | harmonious |
| Quintile | 72° | 5 | 72 | harmonious |
| Square | 90° | 4 | 90 | challenging |
| Trine | 120° | 3 | 120 | harmonious |
| Opposition | 180° | 2 | 180 | challenging |

Aspects are symmetric: a separation of 90° and one of 270° are both squares. The harmonic formulation (§7.3) respects this exactly.

### 3.4 Signs

Sign membership is by tropical longitude, the frame in which the FPOA audit found the stronger result: sign *k* (k = 0 for Aries) spans [30*k*, 30*k* + 30). Polarity — odd signs (Aries, Gemini, Leo, Libra, Sagittarius, Aquarius) are yang, even signs yin. Modality — cardinal: Aries, Cancer, Libra, Capricorn; fixed: Taurus, Leo, Scorpio, Aquarius; mutable: Gemini, Virgo, Sagittarius, Pisces. Element — fire: Aries, Leo, Sagittarius; earth: Taurus, Virgo, Capricorn; air: Gemini, Libra, Aquarius; water: Cancer, Scorpio, Pisces. Sidereal membership (Lahiri ayanāṃśa, ≈ 24.3° at mid-window) is a pre-specified sensitivity alternative (§7.7); unlike aspect angles, sign membership does depend on the frame.

### 3.5 Unnamed control pool

The unnamed-asteroid null (§7.5) uses the 1,211 numbered but unnamed main-belt asteroids whose designations are listed in the first study's `unnamed_mba_full_names.txt`, copied here as `data/unnamed_pool.txt`. Their positions are recomputed for the new window by the same ephemeris procedure as the named bodies. No unnamed body can share a name with anything in the news.

---

## 4. Data source and acquisition protocol

### 4.1 Source and tier

News presence is measured from CLSTR (https://clstr.news), which clusters articles from hundreds of sources into deduplicated, cross-referenced *situations*, each a timeline of member *clusters* (events), exposed through a documented, versioned REST API at `https://api.clstr.news/v1`. CLSTR states that v1 is stable — fields are only added, never renamed or removed within v1, and breaking changes receive a new version prefix with at least 90 days' notice. The API version, request parameters, and response schema are recorded with every pull.

The study subscribes to the **Builder** tier, which imposes three limits: 5,000 requests per day, 60 requests per minute, and 250 searches per day, with a 30-day history window (the widest `days` a request may ask for; larger values are clamped). The daily caps are metered on **distinct requests**: a retry of the same request on the same UTC day is not charged again (verified against the quota headers on 2026-08-30), so the ledgers below count distinct requests, retries are free, and the collector paces against the provider's `X-RateLimit-Remaining-Day` header wherever it has been seen rather than against its own attempt count. The per-minute limit reports no remaining count and is enforced at the edge; the collector spaces its requests globally below that allowance and honours `Retry-After` on any 429. The budget is registered as **two ledgers**, enforced by the collector; the allocation is part of the registration.

**Request ledger — 5,000 distinct requests per day**

| Layer | Endpoint | Ceiling | Purpose |
|---|---|---|---|
| A — census | `GET /situations` | 162 (81 pages × 2 sort orders) | The complete set of situations active in the trailing 24 h |
| B — timelines | `GET /situations/{id}` | 4,300 | The member clusters (events) of every census situation, with text and timestamps |
| C — search | `GET /search` | 250 (the search ledger below) | Embedding-based retrieval for a fixed cohort of names |
| Unallocated | — | ≥ 288 | Headroom; the ledger stops each layer before the cap |

**Search ledger — 250 distinct searches per day**, spent in a strict priority order so that a constrained day degrades in a registered direction:

| Priority | Purpose | Planned |
|---:|---|---:|
| 1 | Back-fill of names missed on earlier days (§4.7) | 10 |
| 2 | The first page for every name in today's cohort | ≤ 225 |
| 3 | Second pages under the §4.4 truncation rule | 15 |
| | **Total** | **250** |

A name with no successful response by the end of the run, its §4.6a end-of-run pass included, is logged `missing` in the day's quality log and enters the back-fill queue.

### 4.2 Layer A — daily census

Once per day at 12:00 UTC the collector requests `GET /situations` with `limit = 50`, `days = 1`, `category = all`, `country = all`, once with `sort = relevance` and once with `sort = recent`, following `next_cursor` in each until the API returns no cursor or the documented ceiling of 81 pages is reached. The union of the two lists, keyed by situation `id`, is the day's census; taking both orders guards against truncation of either ranking. Every page is archived verbatim.

### 4.3 Layer B — cluster timelines

For every situation in the census, in relevance order, the collector requests `GET /situations/{id}` with `timeline_limit = 25` and, if the oldest cluster returned was published inside the day's window, continues with `timeline_before` until a cluster older than the window is reached or four pages have been fetched. Fetching stops when the Layer B budget is exhausted; the fraction of census situations whose timelines were fetched is logged daily and is expected to be 1.0 whenever the census holds fewer than about 4,000 situations. The day's window is [12:00 UTC of the previous day, 12:00 UTC of the pull day); a cluster belongs to day *t* if its `published_at` falls in that window. Every response is archived verbatim.

Cluster-level counting is the principal gain from the Builder tier. A situation can stay active for weeks, so counting a situation on every day it is updated would credit a long-running story to every day of its life and blur the timing that aspect tests depend on; a cluster is a dated event with its own text, significance score, and count of source articles, and is the direct analogue of the first study's daily article counts.

### 4.3a Collection invariant

Layer A selects situations active in the trailing 24 hours (`days = 1`). A situation so selected whose fetched timeline contains no cluster published inside the day's window is contradictory: either the window arithmetic or the timestamp handling is wrong. The collector therefore asserts, on any day where at least one timeline was fetched successfully, that the day's total `clusters_in_window` is at least 1; a day failing the assertion is marked incomplete with `stop_reason = zero_clusters_in_window`.

This assertion tests pipeline integrity, not the value of any outcome variable. It is not a threshold on news volume: no day is excluded for yielding few clusters, only for yielding a count that Layer A's selection criterion makes impossible. The distinction is deliberate, since a completeness rule keyed to outcome magnitude would function as a post hoc exclusion and would bias the series toward high-news days.

### 4.4 Layer C — cohort search

The `GET /search` endpoint performs an embedding-based (semantic) search and is the only endpoint that accepts a name. The 1,122 verified names are assigned once, by a seeded random permutation (seed `20260916`), to five cohorts of 225, 225, 224, 224, and 224 names, committed as `data/search_cohorts.csv` at freeze. On day *t* of the window (day 1 = the first confirmatory pull) the collector queries, for every name in cohort ((*t* − 1) mod 5), `GET /search` with `q = <name>`, `days = 5`, `limit = 30`. Because every name is searched every fifth day with a five-day window, the search layer covers every name on every day, and each result is assigned to a day by its `published_at`. The `/search` page size is capped by the tier at 30 results — a larger `limit` is clamped, not rejected (verified 2026-08-30) — so a first page of 27 or more lexically confirmed matches is likely truncated. Up to 15 second pages (`cursor`) are spent on such names, in cohort order, within the search ledger of §4.1; a name-window whose final page is still 27 or more confirmed matches is flagged *truncated* and treated as missing in search-layer statistics. Every response is archived verbatim.

Semantic retrieval returns the nearest items even when nothing mentions the name, and the response carries no similarity score. The pilot (§8) characterises this behaviour. Layer C serves three pre-registered purposes: its lexically confirmed subset measures the recall of Layers A and B; its unconfirmed remainder — items retrieved for a name that do not contain the name — is archived for exploratory analysis of semantic association; and, with a 30-day history, it allows back-filling of any missed day within 30 days.

### 4.5 Name-matching protocol

A cluster (or situation) matches a name if its text — for clusters, `title` and `summary`; for situations, `title`, `summary_preview`, and `latest_cluster_title` — contains the name as a whole phrase. Both sides are normalised by Unicode NFKD decomposition, removal of combining marks, and case folding. Within a name, a space, hyphen, or apostrophe matches an optional space, hyphen, or apostrophe. The match must begin and end at a boundary between a letter-or-digit and a non-letter-or-digit character, so that "Tyson's" matches "Tyson" and "Tysons" does not. Multi-word names match only as the full phrase. There is no stemming and no alias expansion; the name is matched exactly as it appears in `data/body_names.csv`. Matching is deterministic and re-runnable from the archive at any time.

### 4.6 Daily outcome variables

For body *b* and day *t*, let *M_b*(*t*) be the set of distinct clusters published in window *t*, drawn from the Layer B timelines of the day's census, whose text matches the name. The outcome series are:

*N_b*(*t*) = |*M_b*(*t*)| — the number of matching clusters (the **primary** outcome);

*A_b*(*t*) = Σ over *M_b*(*t*) of `sources` — the number of source articles behind those clusters, the closest analogue of the first study's count (secondary);

*S_b*(*t*) = Σ over *M_b*(*t*) of `significance_score` — significance-weighted presence (secondary);

*N_b*^(q)(*t*) = Σ over *M_b*(*t*) of *P*(*q* | cluster) — presence carrying quality *q*, for every class *q* of every classification axis (§5), so that the classes of an axis partition *N_b*(*t*);

*N_b*^sit(*t*) — the number of census situations (not clusters) matching the name, the situation-level count of the earlier draft, kept as a robustness outcome;

*E_b*(*t*) — the number of lexically confirmed Layer C clusters assigned to day *t*, and *E_b*^+(*t*) the number of confirmed clusters found by Layer C but absent from Layer B (recall shortfall).

H1–H3 use *N*; H4–H8 use the *N*^(q); *A* and *S* are pre-specified secondary outcomes reported with the same statistics.

### 4.6a Error taxonomy

Responses are handled by CLSTR's documented status classes. No class is retried except as named here; the collector's behaviour is exactly this table.

| Status | Retry | Action |
|---|---|---|
| 200 | — | Archive and proceed. |
| 400 `bad_request` | Never | Abort the run; `stop_reason = malformed_request`. A malformed request is a code defect, never a data condition. |
| 401 `unauthorized` | Never | Abort the run; `stop_reason = unauthorized`. A revoked key must never present as a coverage shortfall. |
| 404 `not_found` | Never | A `moved_to` is followed once, both responses archived and the id mapping recorded in the day's quality log; otherwise the situation is recorded as **retired**. |
| 410 `gone` | Never | The situation is recorded as **retired**. |
| 429 `rate_limited` | Conditional | A `Retry-After` of 600 s or less is a burst window: it is waited out and the request re-issued. Above that it is a daily cap: the affected ledger stops for the day and the request is never retried same-day. Which cap fired is read from the quota headers, then from the message. |
| 500 / 502 / 503, network failure | Up to three retries | The server's numeric `Retry-After` is honoured, capped at 120 s; absent one, the schedule is 2, 4, 8, 16 s. A request that exhausts its retries is **deferred**. |

After Layers A–C the collector makes one end-of-run pass over every deferred request. A request that fails the second pass is final for the day; a deferred search becomes `missing` and enters the back-fill queue of §4.7.

A situation recorded as **retired** was present in the Layer A census and withdrawn by the source before Layer B reached it. It is not a collection failure: it leaves the coverage denominator of §4.7 and is listed by id in the day's quality log, so that the exclusion is auditable and the count of retirements is itself monitored for drift.

### 4.7 Archiving, integrity, drift monitoring, and missing data

Every API response — every failed attempt included — is stored unmodified as newline-delimited JSON with its request URL, parameters, HTTP status, request timestamp, and the retained response headers (the `X-RateLimit-*` quota family, `Retry-After`, and the edge identification), under `raw/situations/`, `raw/timelines/`, and `raw/search/` by date; non-200 attempts are stored under `raw/errors/` by date, so that the archive can answer what failed and how, not only what succeeded. A daily manifest records the SHA-256 of every raw file and the SHA-256 of the previous day's manifest, forming a hash chain; manifests are committed to the repository by the automated collector with the run's timestamp. The raw archive — roughly 50 MB a day, too large for a source repository over five years — is held in object storage and deposited monthly on Zenodo as a compressed, immutable, DOI-bearing record whose checksums appear in the repository manifests; the repository itself holds the manifests, the metadata of every matched cluster (identifier, situation, timestamp, significance, sources, category, matched names, link), the daily quality log, and all derived tables. Derived tables (`derived/N.csv`, `A.csv`, `S.csv`, one file per quality class, `N_sit.csv`, `E.csv`, one row per day and one column per name) are regenerated from the raw archive by a single script and never edited by hand.

A daily quality log records pages and situations per sort order, timelines fetched and their coverage fraction, clusters in window, the distribution of `significance_score`, names matched, searches issued and truncations, and a hash of the response schema. A change in the schema hash or a shift of the daily cluster count beyond three median absolute deviations from the trailing 60-day median triggers a review, recorded in the changelog; no review alters the analysis plan.

A day is complete when (a) both census orders were retrieved with HTTP 200 under the retry policy of §4.6a and the final page of each carried no cursor or the 81-page ceiling was reached; (b) the number of eligible census situations whose timelines were not fetched, after the end-of-run pass, does not exceed max(*k*, ⌈0.02 × *N*_eligible⌉), where *N*_eligible excludes situations recorded as retired under §4.6a and *k* = 3 provisionally, to be fixed at freeze from the pilot's measured baseline failure rate (a fixed coverage fraction collapses at a small census: at the observed pre-pilot census of 82, a 0.98 bar tolerated exactly one failure); and (c) the collection invariant of §4.3a held. Layer C does not enter the completeness test: searches missed on a complete day are recovered by back-fill and the day remains complete. Incomplete days are excluded for all bodies from every confirmatory statistic. If more than 5% of days in the window are incomplete, the window is extended day-for-day until 1,826 complete days are obtained. A name missed by Layer C is back-filled within 30 days by the same query with `days` enlarged to cover the missed day's search span, is flagged as back-filled in the quality log, and the back-fill queue is derived from the manifests alone, so that no state exists outside the audited record. The manifest carries a top-level `stop_reason`, null on a complete day and otherwise the first applicable of `malformed_request`, `unauthorized`, `operator_abort`, `request_budget_exhausted`, `time_budget_exhausted`, `layer_a_http_error`, `layer_a_cursor_unexhausted`, `coverage_below_threshold`, `zero_clusters_in_window`; the quality log carries per-layer `ok` flags, per-status error counts, retired and moved situation ids, missing and back-filled searches, the last-seen quota headers, and the collector's version and commit.

---

## 5. Classification of coverage

### 5.1 Axes

Every matched cluster is classified on five axes, each with a fixed label set:

| Axis | Labels | Astrological correlate tested |
|---|---|---|
| Polarity | positive, negative, neutral | Harmonious vs challenging aspects (H4); benefic vs malefic planets (exploratory) |
| Element | space, air, fire, water, earth | Planetary tattva (H5); sign element, four-fold (exploratory) |
| Gender | male, female, not applicable | Planetary gender (H6); sign polarity (exploratory) |
| Yin–yang | yin, yang | Sign polarity (H7); planetary gender (exploratory) |
| Modality | cardinal, fixed, mutable | Sign modality (H8) |

"Not applicable" is added to the gender axis because most news events have no principal human subject, and forcing a binary label on them would manufacture noise; the class is recorded and excluded from H6. The rubric that defines every label is fixed in Appendix C and is the text the classifier sees.

### 5.2 Classifier

Classification is a deterministic function of archived text, applied uniformly at analysis time, so that no drift in any external service can enter the data over five years. The primary classifier is an open-weights instruction-tuned language model run locally with pinned weights and greedy decoding: for each axis, the fixed rubric prompt (Appendix C) followed by the cluster's title and summary is presented, and the label probabilities are taken from the model's next-token distribution restricted to the label set and renormalised. The candidate models are `Qwen/Qwen2.5-7B-Instruct`, `meta-llama/Llama-3.1-8B-Instruct`, and `google/gemma-2-9b-it`; the secondary, non-generative baseline is zero-shot natural-language inference with `facebook/bart-large-mnli`, and for polarity alone `cardiffnlp/twitter-roberta-base-sentiment-latest`. The primary model is chosen during the pilot (§8) by agreement with a blind human calibration set, and its identity, revision hash, prompt hash, and decoding settings are recorded in the changelog before the confirmatory window opens. The chosen model is not changed for the duration of the study; a newer model may be applied afterwards only as an exploratory re-analysis.

Classification is run incrementally on each day's matched clusters and re-run from scratch over the whole archive at each interim analysis; any disagreement between the incremental and the full run is reported, and the full run is the one used. A 1,000-cluster subset is re-classified on a second machine at each interim to quantify hardware-dependent label flips.

### 5.3 Calibration

During the pilot, 300 matched clusters are rated on all five axes by two human raters working blind to every astronomical variable, using the rubric of Appendix C. Cohen's κ between the raters, and between each candidate classifier and the rater consensus, is reported per axis. The classifier with the highest mean κ across axes becomes the primary; an axis on which no candidate reaches κ ≥ 0.4 against the raters is demoted to exploratory before freeze and the corresponding hypothesis is withdrawn, with the decision and its date recorded in the changelog. The calibration set and ratings are published.

---

## 6. Ephemeris and angle encoding

Positions are geocentric apparent ecliptic longitudes of date, in degrees, from JPL Horizons (`https://ssd.jpl.nasa.gov/api/horizons.api`, OBSERVER table, `CENTER = '500@399'`, quantity 31), evaluated daily at 00:00 UTC, the midpoint of each news window. Every aspect quantity is a difference of two longitudes, so the tropical or sidereal reference cancels; sign membership (§3.4) uses the tropical frame. The frame is verified at build time by asserting that the Sun's longitude at the March 2027 equinox lies within 0.05° of 0°.

Each verified name is resolved to its unique minor-planet number through the JPL Small-Body Database and the mapping (name, number, SPK-ID) is committed as `data/body_ids.csv` before the window opens. The major bodies are Horizons targets 10 (Sun), 301 (Moon), 199, 299, 499, 599, 699, 799, 899, and 999. Rahu is the mean longitude of the Moon's ascending node from Meeus, *Astronomical Algorithms*, 2nd ed., Chapter 47, the convention of the first study; Ketu is Rahu + 180°; the true node is computed as a sensitivity alternative. FPOA is 0°.

For each body *b*, reference point *R*, and day *t*, the signed separation θ = (λ_b − λ_R) mod 360 is stored to 0.01° together with cos θ and sin θ, so that every harmonic cosine cos(*n*θ) is available exactly; the integer bin used by the autocorrelation is ⌊θ + 0.5⌋ mod 360. The ephemeris for the whole window — 1,122 named bodies, 1,211 unnamed bodies, thirteen reference points, 1,826 days — is built and committed before the confirmatory window opens and is not regenerated afterwards.

---

## 7. Statistical analysis plan

### 7.1 Data reduction

Each body's outcome series is L2-normalised over the complete days of the window (an all-zero series stays zero), so that every body carries equal total weight and no heavily covered name dominates, as in both predecessor studies; quality-weighted series *N*^(q) are normalised by the norm of the parent series *N* so that the classes of an axis remain a partition of the body's weight. For reference point *R*, the pooled wave *W_R*(θ), θ = 0, …, 359, is the mean of the normalised values over all (body, day) observations whose separation bin is θ. Statistics in §7.3, §7.5, and §7.6 use the pooled (body, day) observations with exact angles; the autocorrelation in §7.4 uses the centred binned wave.

### 7.2 First-harmonic V-statistic (as in the first study)

*V_R*(φ) = Σ_θ *W_R*(θ)·cos(θ − φ) / Σ_θ *W_R*(θ), evaluated at every integer degree for the landscape figure. Because *V_R*(φ) = *a*·cos φ + *b*·sin φ is a projection onto the first harmonic, all 360 values are functions of the two numbers (*a*, *b*): the landscape locates the phase of the first harmonic and nothing more. Its confirmatory use is confined to H3; its phase and amplitude are reported descriptively for every reference point.

### 7.3 Harmonic V-statistic (primary)

For reference point *R*, harmonic *n* ∈ 𝒩 = {1, 2, 3, 4, 5, 6, 7, 8, 12}, and a normalised series *c̃*,

*V_{R,n}*[*c̃*] = Σ_{b,t} *c̃_b*(*t*)·cos(*n*·θ_{b,R}(*t*)) / Σ_{b,t} *c̃_b*(*t*).

This is the Rayleigh V-test on the *n*-fold angle against direction 0; it tests concentration at the family {0, 360/*n*, 2·360/*n*, …}, which contains the aspect and respects its symmetry. Under the aspect hypothesis every *V_{R,n}* is positive. The per-reference statistic is *D_R* = Σ_{n∈𝒩} *V_{R,n}*[*N*], and the omnibus is *D* = Σ_R *D_R* over the twelve independent reference points. The phase-free amplitude *A_{R,n}* = |Σ *c̃*·e^{*in*θ}| / Σ *c̃* and the energy *J_R* = Σ_n *A_{R,n}*² are descriptive companions. Because Fourier components are orthogonal, the nine harmonic statistics of a reference point are asymptotically independent under uniformity.

### 7.4 Circular autocorrelation (replication statistic)

The biased circular autocorrelation of the centred binned wave, computed through the Wiener–Khinchin relation exactly as in the first study, is evaluated at the eight aspect lags {30, 45, 51, 60, 72, 90, 120, 180}. The per-reference statistic is Σ_k ACF(*k*)²; the count *K* of lags exceeding ±1.96/√360 and the Ljung–Box *Q* restricted to the aspect lags are reported for continuity. Their omnibus is the sum over the twelve independent reference points.

### 7.5 Block II statistics on aspects (H4, H5, H6)

Write *D_R*[*c̃*] = Σ_{n∈𝒩} *V_{R,n}*[*c̃*] for the aspect-concentration of any normalised series, and let 𝒩_harm = {12, 6, 5, 3} and 𝒩_chal = {8, 4, 2} be the harmonious and challenging harmonics.

Δ_pol = Σ_R [ Σ_{n∈𝒩_harm} (*V_{R,n}*[*N*^(pos)] − *V_{R,n}*[*N*^(neg)]) − Σ_{n∈𝒩_chal} (*V_{R,n}*[*N*^(pos)] − *V_{R,n}*[*N*^(neg)]) ], summed over the twelve independent reference points.

*G*_elem = Σ_{P} ( *D_P*[*N*^(elem(P))] − *D_P*[*N*^(not elem(P))] ), summed over the seven classical planets, where elem(*P*) is the planet's tattva (§3.2) and *N*^(not elem(P)) is the presence carrying any of the other four elements.

*G*_gen = Σ_{P∈{Sun, Mars, Jupiter}} ( *D_P*[*N*^(male)] − *D_P*[*N*^(female)] ) + Σ_{P∈{Moon, Venus}} ( *D_P*[*N*^(female)] − *D_P*[*N*^(male)] ).

Each statistic is a difference between two series that share the same bodies and days, so any aspect structure common to all coverage cancels and only the differential quality structure remains.

### 7.6 Block II statistics on signs (H7, H8)

Let *L_b*(*t*) be the body's tropical longitude (its separation from FPOA) and define the phase-locked harmonic projection *U_h*[*c̃*](φ) = Σ_{b,t} *c̃_b*(*t*)·cos(*h*·(*L_b*(*t*) − φ)) / Σ *c̃*.

Sign polarity alternates every 30°, a sixth-harmonic pattern whose yang sign centres lie at 15°, 75°, 135°, 195°, 255°, 315°: *Y* = *U*_6[*N*^(yang)](15°) − *U*_6[*N*^(yin)](15°).

Sign modality repeats every 90°, a fourth-harmonic pattern with cardinal centres at 15°, 105°, 195°, 285°, fixed centres at 45°, …, and mutable centres at 75°, …: *M* = *U*_4[*N*^(cardinal)](15°) + *U*_4[*N*^(fixed)](45°) + *U*_4[*N*^(mutable)](75°). The three phases are 120° apart in fourth-harmonic phase, so any fourth-harmonic structure shared by all coverage sums to zero and *M* isolates the differential modality structure. The analogous four-element sign statistic *F* = *U*_3[*N*^(fire)](15°) + *U*_3[*N*^(earth)](45°) + *U*_3[*N*^(air)](75°) + *U*_3[*N*^(water)](105°), with the space class omitted and the remaining four renormalised, is exploratory.

### 7.7 Null models, inference, and multiplicity

Two count-preserving Monte Carlo nulls are used, 5,000 replicates each, seed 42 as in the predecessors, with results at seeds 1, 2, and 3 reported as a stability check.

The **compound null** permutes which body carries which normalised outcome series and rolls each series by an independent uniform random circular shift in time, destroying any name-to-orbit registration while preserving every body's orbital geometry, every series' marginal distribution, and the temporal autocorrelation within series. All series belonging to a body — *N*, *A*, *S*, and every *N*^(q) — are permuted and rolled together, so that the classes of an axis stay attached to their parent counts.

The **unnamed-asteroid null** re-bins the real normalised series onto the orbits of 1,122 asteroids drawn without replacement, on each replicate, from the 1,211-body unnamed pool, preserving the counts, their classifications, and the news calendar exactly, and replacing only the orbits with those of bodies that cannot share a name with anything in the news.

Monte Carlo *p*-values are (1 + number of replicates ≥ observed) / (1 + 5,000), one-sided in the predicted direction for every Block I and Block II statistic and for larger values of the autocorrelation statistics. Standardised effects *d* = (observed − null mean) / null SD are reported for every statistic, and the modulation amplitude of the first harmonic is reported as a percentage of the all-angle mean, as in the FPOA audit. The pragmatic Bayes factor 1/(2*p*) used by the first study is reported for continuity but is descriptive; inference rests on the Monte Carlo *p*-values.

A confirmatory hypothesis is supported only if its statistic exceeds both nulls. H1 and H3 are tested at α = 0.05; H2 at α = 0.05/12; H4–H8 at α = 0.01 each. Within the exploratory analyses, Benjamini–Hochberg control at *q* = 0.10 is applied within each family, and every such result is labelled exploratory.

Pre-specified robustness checks: each confirmatory statistic is recomputed (a) excluding the eighteen verified names of three characters or fewer; (b) excluding the twelve names (≈ 1%) with the greatest total presence; (c) excluding names that are entries in a fixed English word list committed at freeze; (d) with the true lunar node in place of the mean node; (e) with the ephemeris epoch at 12:00 UTC; (f) with the septile lag at 52°; (g) using *A* and *S* in place of *N*; (h) using *N*^sit in place of *N*; (i) with sidereal (Lahiri) sign membership for H7 and H8; (j) with the secondary classifier in place of the primary for H4–H8; (k) per calendar year of the window, as five independent replications; and (l) using the union of Layer B and lexically confirmed Layer C clusters. None substitutes for the confirmatory result; they qualify its interpretation.

### 7.8 Exploratory analyses

Everything not named above is exploratory: the full 360-direction V landscapes; per-aspect and per-harmonic breakdowns; Ketu's derived results; benefic–malefic contrasts of polarity; four-element sign statistics and planetary-gender contrasts of yin–yang; element and modality of coverage against the outer planets and nodes; the semantic-association remainder of Layer C; analyses using *E* and *E*⁺; category- and country-restricted subsets; the relation between orbital speed and effect; and any analysis suggested by the data.

---

## 8. Timeline, interim analyses, and stopping rule

| Milestone | Proposed date | Content |
|---|---|---|
| Version 0.1 committed | 2026-08-28 | First draft (three-year window, Free tier). |
| Version 0.2 committed | 2026-08-28 | Builder tier, five-year window, five classification axes, cluster-level outcome. |
| Version 0.3 committed | 2026-08-30 | This draft: error taxonomy, two ledgers, completeness allowance, collection invariant — prompted by the pre-pilot shakedown runs of 2026-08-29/30 (`PILOT_FINDINGS_2026-08-30.md`). Those runs precede the pilot, are marked incomplete under version 0.2, and are kept in the manifest chain with no standing in any analysis. |
| Pilot | first 14 days of successful pulls (target 2026-09-01 to 2026-09-14) | Characterise census sizes, `days = 1` semantics, timeline coverage, name-match rates, `/search` behaviour and truncation; build the 300-cluster calibration set; choose the classifier; fix operational definitions. Pilot data are quarantined from every confirmatory analysis. |
| Freeze, version 1.0 | by 2026-09-15 | Analysis code tagged; ephemeris, `body_ids.csv`, `search_cohorts.csv`, word list, classifier identity, and rubric hash committed; document time-stamped (§10); simulation-based power analysis added as an appendix. |
| Confirmatory window | 2026-09-16 through 2031-09-15, inclusive | 1,826 complete days (five calendar years including 2028-02-29). |
| Interim reports | day 290 (2027-07-02), day 365 (2027-09-15), day 731 (2028-09-15), day 1,096 (2029-09-15), day 1,461 (2030-09-15) | Full analysis run and published, labelled interim. |
| Final analysis | after the last complete day | The single confirmatory run. |

The window is fixed by date, not by outcome. Interim reports do not stop, shorten, or extend the study and do not alter the plan; the only permitted extension is the day-for-day replacement of incomplete days (§4.7). Collection may continue after the window for future work, but the confirmatory analysis uses the registered window only.

Why five years: a typical main-belt asteroid (semi-major axis 2.7 AU, period 4.4 years) drifts about 81° per year in longitude. The table gives the mean separation swept per body relative to each reference point in the first study's window and in the present one.

| Reference point | 290 days (first study) | Five years (this study) |
|---|---|---|
| Moon | ≈ 3,760° (10.4 cycles) | ≈ 23,700° (66 cycles) |
| Sun, Mercury, Venus | ≈ 220° (0.6 cycle) | ≈ 1,390° (3.9 cycles) |
| Mars | ≈ 90° (0.2 cycle) | ≈ 550° (1.5 cycles) |
| Rahu, Ketu | ≈ 80° (0.2 cycle) | ≈ 500° (1.4 cycles) |
| FPOA, Uranus, Neptune, Pluto | ≈ 60–65° (0.2 cycle) | ≈ 385–405° (1.1 cycles) |
| Saturn | ≈ 55° (0.15 cycle) | ≈ 345° (1.0 cycle) |
| Jupiter | ≈ 40° (0.1 cycle) | ≈ 255° (0.7 cycle) |

In the first study the Moon was the only reference point that every body had lapped many times; its wave was the best averaged, and it was also the one reference point that showed no structure and served as the negative control. Five years brings every reference point except Jupiter to at least one full aspect cycle per body, and the inner references to nearly four, so that day-to-day noise is averaged down and any structure that survives is both more credible and more precisely estimated. Coverage of the pooled wave is complete for every reference point even at 290 days, because the 1,122 bodies are spread around the ecliptic; the longer window buys more independent aspect events per body, five within-study replications by calendar year (§7.7(k)), and, for the sign hypotheses, a full circuit of the zodiac by every body.

---

## 9. Improvements over the first study

**Prospective, time-stamped registration.** The first study's analysis plan was written after its counts existed. Here the declaration of intent, the hypotheses, the statistics, the nulls, the thresholds, the classification rubric, and the exclusion rules are committed and independently time-stamped before the first confirmatory observation, and every subsequent change is dated in the changelog. The target cannot be moved after the results are in, and a reader can verify that it was not.

**A stable, uniform data interface.** Google News result counts were an undocumented quantity that could change definition silently over the 290 days. CLSTR's v1 API is documented, versioned, and covered by a published stability commitment; the same requests are issued the same way every day, the raw responses are archived and hash-chained, and every derived number is regenerable from the archive by one script.

**Semantic retrieval alongside lexical matching.** An embedding-based search recovers coverage that a strict string match misses — paraphrase, transliteration, and context — and its ranking carries information that a hit count does not. The Builder tier allows it to be applied to every name on every day through a five-cohort rotation, with its limits (no similarity score; neighbours returned even without a mention) stated in advance and its confirmatory role settled by the pilot rather than by the results.

**A transparent index in place of a black box.** CLSTR situations and clusters are deduplicated, cross-source, multi-article events with explicit fields — significance, source counts, category, country, and timestamps — rather than an opaque count whose composition was whatever the provider's ranking made it on the day. Counting dated clusters rather than result pages gives each day's presence a defined meaning.

**Significance and the qualities of coverage.** Each cluster's significance score, and five pre-registered classifications computed from its archived text — polarity, element, gender of subject, yin–yang character, and modality — allow presence to be weighted by how much a story mattered and separated by what kind of story it was. This makes it possible to ask, for the first time in this line of work, whether the harmonious and challenging aspects differ in the polarity of the coverage they coincide with, whether the element and gender tradition assigns to a planet appear in the coverage at aspects to that planet, and whether the polarity and modality of the sign a body occupies appear in the coverage of its namesake, rather than pooling all coverage into one undifferentiated count.

**A window of five years rather than 290 days.** The coverage table in §8 quantifies what this buys: at least one full aspect cycle per body for every reference point but Jupiter, nearly four for the inner references, a complete circuit of the zodiac for the sign hypotheses, and five within-study replications by calendar year.

**Further improvements introduced in this design.** A harmonic V-statistic that tests each aspect as the harmonic it is, resolving the multi-lobed structure that a first-harmonic V-test cannot see and that the FPOA audit showed the earlier aspect-lag autocorrelations had collapsed into one cosine. Differential statistics for the quality hypotheses that cancel whatever aspect or sign structure is common to all coverage. An explicit division of confirmatory from exploratory analyses, with multiplicity control stated in advance. A classifier that is a deterministic function of archived text with pinned weights, calibrated against blind human ratings, with an axis-level demotion rule fixed before freeze. A pilot phase on quarantined data. A frozen ephemeris and frozen identifier and cohort tables built before the window opens. Automated daily collection with an append-only, hash-chained archive, monthly immutable deposits, and drift monitoring. Exact-angle statistics with cosines stored, alongside the binned autocorrelation. Rahu, Ketu, and FPOA all included, with the Rahu–Ketu dependence made explicit. Pre-specified missing-data and back-fill rules. Twelve sensitivity analyses named before the data exist. A direct out-of-sample replication of the FPOA–Libra axis result as a confirmatory test. A simulation-based power analysis and smallest effect of interest to be added at freeze. Public code and data under an open licence with citable DOIs at freeze, at each monthly deposit, and at completion.

---

## 10. Time-stamping and version control

Every version of this document is committed to the public repository with a signed commit. At freeze, the SHA-256 digest of `PREREGISTRATION.md` (version 1.0) is written to `PREREGISTRATION.sha256`, anchored with OpenTimestamps (the `.ots` proof is committed), registered as a frozen pre-registration on OSF Registries, and archived with the repository snapshot on Zenodo, which issues a DOI. The daily commits made by the automated collector carry the platform's server-side timestamps; the hash chain of daily manifests (§4.7) and the monthly Zenodo deposits make any retroactive alteration of the archive detectable. The frozen text is never edited; corrections and decisions are appended to the changelog with their dates, and a new version number is issued only for changes that affect the plan.

---

## 11. Data, code, attribution, and disclosures

Code and derived data are released under the repository's MIT licence. Derived tables, identifiers, slugs, timestamps, significance and source counts, classifications, and links to CLSTR situations and clusters are public. Publication of archived titles and summaries is contingent on written permission from CLSTR, which will be requested during the pilot; until then the raw text archive is held privately, the monthly Zenodo deposits are restricted-access records whose checksums and DOIs are public, and the text is made available to reviewers on request. Every public table and figure links to clstr.news. Ephemerides are from JPL Horizons; the lunar-node formula is from Meeus (1998); planetary attributes are from Bṛhat Parāśara Horā Śāstra. No API credential, personal information, or private configuration is committed to the repository; credentials are held as repository secrets. The study is self-funded; the API subscription is the only recurring cost.

The principal investigator is a practitioner and teacher of the tradition whose claims are under test. The design's purpose is to make that immaterial: the hypotheses, statistics, thresholds, and rubric are fixed before the data exist, the human calibration raters work blind to every astronomical variable, the analysis is a single scripted run, and the null models are the same two that the first study used against itself.

---

## 12. Decisions to be locked at freeze

The daily pull time: 12:00 UTC is proposed. The runtime: an automated workflow in the public repository is proposed, with a scheduled job on a local machine as fallback; either records its own timestamps. The confirmatory start date: 2026-09-16, contingent on a completed pilot. The classifier: chosen by §5.3. The primary node: mean node. The object store and the Zenodo community for the raw archive. The publication of raw text: contingent on CLSTR's permission. The English word list for §7.7(c). Any axis demoted under §5.3. The failure allowance *k* of §4.7, from the pilot's measured baseline failure and retirement rates. Confirmation from the pilot that the caps meter distinct requests as observed on 2026-08-30, once a 429 has been seen with its quota headers.

---

## 13. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-08-28 | Initial draft committed for review before freeze (three-year window, Free tier, situation-level outcome, single valence score). |
| 0.2 | 2026-08-28 | Builder tier adopted with a registered daily budget; census taken in two sort orders; cluster timelines fetched and the primary outcome moved to dated clusters; five-cohort search rotation covering every name every day; window extended to five years (1,826 days) with five interim reports; classification expanded to five axes with a fixed rubric, a pinned local classifier, human calibration, and a demotion rule; hypotheses H5–H8 added and H4 restated in harmonic form; Zenodo monthly deposits and a 5% missing-day rule added. |
| 0.3 | 2026-08-30 | Error taxonomy added as §4.6a, aligning collector behaviour with CLSTR's published status classes: no retry of final 4xx, `moved_to` followed once, a *retired* category for 410 and un-redirected 404, daily-cap 429s stop the affected ledger, and an end-of-run second pass over 5xx give-ups. Every failed attempt and the response headers now archived (`raw/errors/`), after the pre-pilot outage left the 503s of 2026-08-30 uncharacterisable. Completeness restated as an absolute failure allowance max(*k*, ⌈0.02 × *N*_eligible⌉) over a denominator that excludes retired situations, the fixed 0.98 fraction having proved infeasible at the observed census of 82; the §4.3a collection invariant added as a completeness criterion after 49 fetched timelines yielded zero clusters in window (a timeline-envelope parsing defect, fixed and pinned by test against the live response shape). Daily budget restated as two ledgers with the metered unit made explicit (distinct requests; retries free — observed against the quota headers); Layer C given a priority order, a back-fill reserve of 10 derived from the manifests alone, second pages capped at 15, and the same worker pool as Layer B; `/search` page size confirmed clamped at 30, so the five-cohort rotation is retained. `stop_reason` enumerated; per-layer `ok` flags, error-class counts, retired/moved ids, and quota headers added to the quality log. Layer C removed from the completeness test (missed searches are back-filled). Prompted by the pre-pilot runs of 2026-08-29/30, recorded in `PILOT_FINDINGS_2026-08-30.md`. |

---

### Appendix A — Files this declaration refers to

`config/study.yaml` (every registered parameter in machine-readable form; the reference points with their classical attributes and the aspect table live here), `config/rubric.yaml` (the classification rubric, Appendix C, whose SHA-256 is the prompt hash), `data/body_names.csv` (1,211 names with the `verified` flag), `data/unnamed_pool.txt` (1,211 unnamed designations), `data/search_cohorts.csv` (the five cohorts, seeded), `data/body_ids.csv` (name → number → SPK-ID, at freeze), `data/ephemeris/` (daily longitudes for the window, at freeze), `raw/` (verbatim API responses, failed attempts under `raw/errors/`; in object storage and Zenodo, hashed in the manifests), `manifests/` (daily SHA-256 manifests, hash-chained), `derived/` (regenerated outcome tables and matched-cluster metadata), `classified/` (per-cluster label probabilities), the `mpclstr` package — `collect.py` (daily collector), `ephemeris.py`, `derive.py` (archive → outcome tables), `classify.py` (rubric prompts and pinned classifier), `stats.py` (estimators and nulls), `analysis.py` (the single confirmatory run), `synthetic.py` and `mock_api.py` (test doubles) — `tests/` (the suite that must pass at freeze), `results/` (summary JSON and null draws), and `PREREGISTRATION.sha256` with its `.ots` proof.

### Appendix B — Request parameters, verbatim

Layer A: `GET https://api.clstr.news/v1/situations?limit=50&days=1&sort=relevance&category=all&country=all[&cursor=…]` and the same with `sort=recent`, each paged to exhaustion or 81 pages.
Layer B: `GET https://api.clstr.news/v1/situations/{id}?timeline_limit=25[&timeline_before=…]`, up to four pages per situation, stopping at the first cluster older than the window.
Layer C: `GET https://api.clstr.news/v1/search?q=<name>&days=5&limit=30[&cursor=…]`, one request per cohort name, a second page only under the §4.4 rule.
Authentication by bearer token; the token is never logged or committed.

### Appendix C — Classification rubric (the text the classifier sees)

The classifier receives, for each axis separately, the following instruction, then the cluster's title and summary, then the request for a single label. Label probabilities are read from the model's next-token distribution over the label words.

*Common preamble.* "You will read the title and summary of one news event. Classify the event on the axis described below. Answer with exactly one label from the list. Judge the event itself as described, not the source or the writing style."

*Polarity — labels: positive, negative, neutral.* "Positive: the event is good news for the people principally affected — gains, recoveries, achievements, rescues, agreements, awards, cures, reconciliations. Negative: the event is bad news for them — harm, loss, death, injury, conflict, crime, failure, disaster, scandal, decline. Neutral: announcements, routine proceedings, scheduling, mixed outcomes, or events with no clear beneficiary or victim."

*Element — labels: space, air, fire, water, earth.* "Space: the abstract, the vast, and the cosmic — astronomy and space exploration, religion and philosophy, mathematics and theory, music and sound, emptiness, openings, vacancies, and things that transcend material form. Air: motion and communication — transport, aviation, wind and weather, migration and travel, logistics, media, telecommunications, information networks, language, debate, and the exchange of ideas. Fire: energy and force — war, weapons, violence, explosions, wildfire, heat, light, power generation, leadership and ambition, sport and competition, anger, and transformation by force. Water: fluids, feeling, and care — oceans, rivers, rain, floods and drought, shipping, health and medicine, emotion, family and relationships, nurturing, fertility, food and drink, compassion, and grief. Earth: matter and resources — money, markets, business, property, agriculture, mining, construction, infrastructure, land, manufacturing, material goods, and the body as a physical object."

*Gender — labels: male, female, not applicable.* "Male: the principal human subject of the event — the person the event is chiefly about — is a man or boy. Female: the principal human subject is a woman or girl. Not applicable: there is no principal human subject, the principal subjects are a mixed or unspecified group, or the subject is an organisation, place, thing, or abstraction."

*Yin–yang — labels: yin, yang.* "Yang: the event's predominant character is active, outward, assertive, initiating, expanding, public, bright, hot, competitive, or forceful. Yin: the event's predominant character is receptive, inward, yielding, sustaining, contracting, private, dark, cool, cooperative, protective, or enduring. Choose the character that better describes what is happening, even if both are present."

*Modality — labels: cardinal, fixed, mutable.* "Cardinal: something is initiated — a launch, a start, a decision taken, an outbreak, a first move, an opening, a crisis erupting, a new leadership or direction. Fixed: something persists or is held — entrenchment, resistance to change, a stalemate, consolidation, endurance, maintenance, accumulation, a standing condition continuing. Mutable: something changes form or passes — transition, adaptation, negotiation, dispersal, fluctuation, an ending or hand-over, learning, reassessment, or an unsettled and shifting state."

### Appendix D — Data dictionary for derived tables

Every derived table is a CSV with a `date` column (the pull date, UTC) followed by one column per verified name in `data/body_names.csv` order. `N.csv`: matched clusters in window. `A.csv`: source articles behind them. `S.csv`: summed significance. `N_pos.csv`, `N_neg.csv`, `N_neu.csv`; `N_space.csv`, `N_air.csv`, `N_fire.csv`, `N_water.csv`, `N_earth.csv`; `N_male.csv`, `N_female.csv`, `N_na.csv`; `N_yin.csv`, `N_yang.csv`; `N_cardinal.csv`, `N_fixed.csv`, `N_mutable.csv`: quality-weighted presence, the classes of each axis summing to `N.csv`. `N_sit.csv`: matching census situations. `E.csv`, `E_plus.csv`: Layer C confirmed clusters and Layer C-only clusters. `complete.csv`: one row per date with the completeness flag and the quality-log fields of §4.7. `derived/matched_clusters.csv`: one row per matched cluster with identifier, situation, `published_at`, `significance_score`, `sources`, category, countries, matched names, and link. `classified/clusters.csv`: one row per matched cluster with the label probabilities on all five axes, the classifier identity, and the rubric hash.
