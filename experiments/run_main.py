"""Main comparison: four baselines, BRISK and its ablations on the default scenario
(6 CAF fields = 252 soil nodes + 6 weather stations, 120 days, 1 gateway).

    python experiments/run_main.py --seeds 10
Writes results/raw/main.csv and per-task logs in results/raw/tasks_main/.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import POLICIES, ROOT, cli, run_jobs, seeds  # noqa: E402


def jobs(n_seeds: int, names=None):
    names = names or list(POLICIES)
    return [{"experiment": "main", "policy": p, "seed": s, "keep_tasks": True}
            for s in seeds(n_seeds) for p in names]


if __name__ == "__main__":
    a = cli()
    out = a.out or os.path.join(ROOT, "results", "raw", "main.csv")
    run_jobs(jobs(a.seeds), out, a.config, a.procs, os.path.join(ROOT, "results", "raw", "tasks_main"))
