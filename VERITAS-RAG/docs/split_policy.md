# Split policy and contradiction clusters

## Problem
The Phase 3 candidates had a single contradiction/qualification group (LoRA claims in paper 1, qualified by papers 6 and 7). Splitting by cluster (needed to avoid leakage) would put all contradiction evidence into one split, leaving the other with none.

## Decision (machine-checked; status: PLANNED, nothing is included yet)
* **Leakage unit = `cluster_id`.** All papers of a cluster go to one split.
* **Contradiction cluster** = a cluster with at least one paper `evidence_role: claim` and one `evidence_role: qualifies`.
* Required: each of `dev` and `test` has at least one contradiction cluster lying wholly inside it; no contradiction cluster spans two splits (`contradiction_coverage_problems`, shown by `python -m app.cli validate-manifest`).
* **Planned assignment** (`planned_split`, a proposal until you confirm):

| Cluster | Papers | Role | Planned split |
|---|---|---|---|
| lora-family | arxiv-2106.09685 (claim), arxiv-2305.14314 (claim), arxiv-2405.09673 (qualifies), arxiv-2410.21228 (qualifies) | richer cluster: two qualifiers | **test** |
| soft-prompts | arxiv-2101.00190 (claim), arxiv-2104.08691 (claim), arxiv-2110.07602 (qualifies) | second, independent cluster | **dev** |
| adapters | arxiv-1902.00751 | singleton; version-discrepancy example | train |

* An included paper's `split` must equal its `planned_split` (changing it is a deliberate edit); questions' gold papers must lie in the question's split (`check_split_consistency`); the retrieval index holds all included papers (other splits act as distractors).
* **Cross-cluster citations:** papers cite each other (e.g. the LoRA paper compares with prefix-tuning and prompt tuning). Rule: a question is assigned to the split of the paper(s) holding its gold evidence; questions whose gold evidence spans clusters of different splits are excluded, not duplicated.

## Honest limits
* One contradiction cluster per split: results on contradiction detection are **case-study level**, with no claim of generalisation, and thresholds tuned on `dev` cannot be validated on a second independent dev cluster.
* The roles come from abstracts read by the assistant (not full-text reading) and must be confirmed by you after reading the papers.
* The clusters are on the same broad PEFT topic, so topical leakage cannot be excluded.
* Plan to add at least one more verified contradiction cluster to each split before the final evaluation.
