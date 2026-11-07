#!/usr/bin/env bash
# Full evaluation (about 3 h on 2 cores).  Results are appended; reruns skip finished jobs.
set -euo pipefail
cd "$(dirname "$0")/.."
python experiments/run_main.py --seeds 10
python experiments/run_pareto.py --seeds 10
python experiments/run_sensitivity.py --seeds 5
python experiments/run_scalability.py --seeds 5
python experiments/make_tables_figures.py
