# BRISK — decision-proximity retrieval and slack-aware placement for cloud-enabled agricultural LoRa sensor networks

This repository contains the trace-driven simulator, the proposed policy (**BRISK**), four
baselines, six ablations, the experiment scripts, the run logs and the LaTeX source of the
manuscript.

> **What this is.** A discrete-event *simulation* study driven by real public traces
> (soil-moisture observations, LoRa loss statistics, weather records, cloud-load shape).
> It is not a field deployment; radio energy is estimated from datasheet currents.

## Layout

```
config/default.yaml          all parameters, with provenance tags [D]/[S]/[L]/[M]/[A]
src/preprocessing.py         dataset cleaning, QC, loss-model fitting (two-receiver decomposition)
src/data_loading.py          fields, thresholds, zones, weather, links, Azure load
src/network_model.py         LoRa air time, Gilbert-Elliott links, gateway (collisions, half-duplex, duty cycle), backhaul
src/retrieval.py             tolerances, send-on-delta, bounded-error replica, interval quorum
src/resource_scheduler.py    edge/fog/cloud tiers (preemptive EDF / FIFO), Azure background, placement
src/task_model.py            task tuple
src/simulator.py             discrete-event engine wiring all layers
src/proposed_algorithm.py    BRISK and its ablations
src/baseline_algorithms.py   CLOUD-PER, EDGE-PER, SOD-PT, SOD-PULL
src/metrics.py               metric definitions and per-run summary
src/analytics.py             task kernels used for profiling
experiments/                 run_main / run_baselines / run_proposed / run_ablation / run_pareto /
                             run_sensitivity / run_scalability / characterize_data / profile_tasks /
                             make_tables_figures, run_all.sh
tests/                       unit tests (pytest)
results/raw/                 one CSV row per simulation run (+ per-task logs of the main study)
results/processed/, tables/  aggregates, paired statistics, characterisation tables
docs/                        architecture, methodology, reproducibility, literature matrix, reference log
data/README.md               how to download the five datasets (not redistributed)
```

## Quick start

```bash
pip install -r requirements.txt
# download the datasets into data/raw/ as described in data/README.md
python -m src.preprocessing --raw data/raw --out data/processed
python -m pytest -q tests
python experiments/run_proposed.py --config config/default.yaml --seeds 1      # one BRISK run (~1 min)
python experiments/run_baselines.py --config config/default.yaml --seeds 1
bash experiments/run_all.sh                                                    # full study (~4 h, 2 cores)
cd paper && latexmk -pdf main.tex
```

All tables, result figures and in-text numbers of the paper are regenerated from
`results/raw/*.csv` by `python experiments/make_tables_figures.py`.  See
`docs/reproducibility.md`.

## Policies

| Name | Retrieval | Verification | Placement |
|---|---|---|---|
| CLOUD-PER | periodic | point | cloud, FIFO |
| EDGE-PER | periodic | point | urgent edge (EDF), analytics cloud |
| SOD-PT | send-on-delta, fixed eps / heartbeat | point | urgent edge, analytics cloud |
| SOD-PULL | send-on-delta, fixed; all nodes Class B | interval + pull all uncertain | min-ECT |
| **BRISK** | proximity heartbeat/tolerance + energy queue; deadline-spanning alarm retries | loss-aware interval quorum (+ point fallback) | urgent min-ECT, strategic cost-feasible |

## Licence

Code: MIT (see `LICENSE`).  Datasets: their own terms (see `data/README.md`).
