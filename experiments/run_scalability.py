"""Scalability: 6, 12, 24 CAF fields per gateway (252-1008 nodes), 60-day horizon.
Fields beyond six replay the same CAF years shifted by whole weeks (load scaling;
event statistics of those fields are not independent).
    python experiments/run_scalability.py --seeds 5
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import ROOT, cli, run_jobs, seeds  # noqa: E402


def jobs(n):
    J = []
    for s in seeds(n):
        for K in (6, 12, 24):
            for p in ("EDGE-PER", "SOD-PT", "SOD-PULL", "BRISK"):
                J.append(dict(experiment="scale", policy=p, label=p, variant=f"tiles={K}", seed=s,
                              cfg={"tiles": K, "horizon_hours": 1440}))
    return J


if __name__ == "__main__":
    a = cli()
    run_jobs(jobs(a.seeds), a.out or os.path.join(ROOT, "results", "raw", "scalability.csv"), a.config, a.procs)
