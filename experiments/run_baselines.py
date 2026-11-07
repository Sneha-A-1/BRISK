"""Baselines only (subset of run_main): python experiments/run_baselines.py --seeds 10"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_main import jobs  # noqa: E402
from runner import ROOT, cli, run_jobs  # noqa: E402
from src.baseline_algorithms import BASELINES  # noqa: E402

if __name__ == "__main__":
    a = cli()
    run_jobs(jobs(a.seeds, list(BASELINES)), a.out or os.path.join(ROOT, "results", "raw", "main.csv"),
             a.config, a.procs, os.path.join(ROOT, "results", "raw", "tasks_main"))
