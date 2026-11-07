"""BRISK only (subset of run_main): python experiments/run_proposed.py --config config/default.yaml"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from run_main import jobs  # noqa: E402
from runner import ROOT, cli, run_jobs  # noqa: E402

if __name__ == "__main__":
    a = cli()
    run_jobs(jobs(a.seeds, ["BRISK"]), a.out or os.path.join(ROOT, "results", "raw", "main.csv"),
             a.config, a.procs, os.path.join(ROOT, "results", "raw", "tasks_main"))
