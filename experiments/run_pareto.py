"""Energy-accuracy trade-off curves (10 seeds): fixed-heartbeat send-on-delta (SOD-PT)
for H in {2,3,6,12,24} h versus BRISK for (H_min, H_max) in a grid, plus periodic
reporting.  Writes results/raw/pareto.csv.
    python experiments/run_pareto.py --seeds 10
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import ROOT, cli, run_jobs, seeds  # noqa: E402


def jobs(n):
    J = []
    for s in seeds(n):
        for hb in (2, 3, 6, 12, 24):
            J.append(dict(experiment="pareto", policy="SOD-PT", label="SOD-PT", variant=f"H={hb}h",
                          seed=s, pol={"hb_s": hb * 3600}))
        for lo, hi in ((1, 6), (1, 12), (2, 12), (3, 24), (6, 24), (6, 48)):
            J.append(dict(experiment="pareto", policy="BRISK", label="BRISK", variant=f"H={lo}-{hi}h", seed=s,
                          cfg={"sensing": {"hb_min_s": lo * 3600, "hb_max_s": hi * 3600}}))
    return J


if __name__ == "__main__":
    a = cli()
    run_jobs(jobs(a.seeds), a.out or os.path.join(ROOT, "results", "raw", "pareto.csv"), a.config, a.procs)
