# Reproducing the results

    pip install -r requirements.txt
    # 1. download the datasets into data/raw/ (see data/README.md)
    python -m src.preprocessing --raw data/raw --out data/processed      # ~5 min
    python -m pytest -q tests                                             # unit tests
    python experiments/characterize_data.py                              # Sec. 6.1 tables/figure
    python experiments/profile_tasks.py                                  # task work values (idle machine)
    bash experiments/run_all.sh                                          # ~4 h on 2 cores
    cd paper && latexmk -pdf main.tex                                    # compile the manuscript

`run_all.sh` runs `run_main.py` (11 policies x 10 seeds), `run_pareto.py` (11 settings x 10
seeds), `run_sensitivity.py` and `run_scalability.py` (5 seeds), then
`make_tables_figures.py`, which regenerates every table (`paper/generated/*.tex`), every
results figure (`paper/figures/*.pdf`) and every in-text number (`paper/generated/macros.tex`)
from `results/raw/*.csv`.  Runs are appended; an interrupted run resumes and skips finished
(policy, variant, seed) jobs.  Individual subsets: `run_baselines.py`, `run_proposed.py`,
`run_ablation.py`.

Determinism: all randomness derives from the seed (numpy Generator); seeds 1000-1009.  Results
were produced with Python 3.13.16 and the versions in `requirements.txt`; different numpy
versions may change random streams but not the conclusions.
