"""mpclstr — pipeline for the second minor-planet-namesakes study.

Modules
-------
config        registered parameters (config/study.yaml, config/rubric.yaml)
matching      the name-matching protocol (PREREGISTRATION §4.5)
cohorts       the five search cohorts (§4.4)
clstr_client  paced, budgeted, logged client for the CLSTR v1 API
collect       the daily collector: census, timelines, cohort search, manifests (§4)
derive        raw archive -> daily outcome tables (§4.6)
classify      rubric prompts and the pinned classifier (§5)
ephemeris     JPL Horizons longitudes and Meeus lunar nodes (§6)
angles        separations, harmonics, sign membership (§6, §3.4)
stats         estimators and the two Monte Carlo nulls (§7)
analysis      the single confirmatory run (§7)
"""

__version__ = "0.2.0"
