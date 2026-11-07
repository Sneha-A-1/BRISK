"""Sensitivity and scenario studies (one CSV row per run in results/raw/sensitivity.csv).

  budget     tighter BRISK energy budgets (10% and 25% of periodic radio energy)
  gateways   second gateway (receiver diversity, UWA two-receiver statistics)
  linkiid    memoryless losses with the same marginal PDR (burstiness ablation)
  deadline   longer urgent deadlines (300 s, 600 s): when does time diversity help?
  backhaul   degraded rural backhaul, with and without a fog server
  analytics  heavier strategic analytics (x4, x16) without fog under degraded backhaul
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from runner import ROOT, cli, run_jobs, seeds  # noqa: E402

BAD_BH = {"backhaul": {"bad": {"rate_bps": 20000, "rtt_s": 0.6}, "mean_good_s": 7200, "mean_bad_s": 3600}}


def jobs(n):
    J = []
    for s in seeds(n):
        for beta in (0.1, 0.25):
            J.append(dict(experiment="budget", policy="BRISK", label="BRISK", variant=f"budget={beta}",
                          seed=s, cfg={"retrieval": {"energy_budget_frac": beta}}))
        for p in ("EDGE-PER", "SOD-PT", "BRISK", "BRISK-stdRetry"):
            J.append(dict(experiment="gateways", policy=p, variant="G=2", seed=s, cfg={"gateways": 2}))
            J.append(dict(experiment="linkiid", policy=p, variant="iid", seed=s, cfg={"link_model": "iid"}))
        for D in (300, 600):
            for p in ("SOD-PT", "BRISK", "BRISK-stdRetry"):
                J.append(dict(experiment="deadline", policy=p, variant=f"D={D}", seed=s,
                              cfg={"events": {"deadline_dry_s": D, "deadline_wet_s": D // 2,
                                              "deadline_weather_s": D // 2}}))
        for fog in (True, False):
            for p in ("CLOUD-PER", "EDGE-PER", "SOD-PULL", "BRISK", "BRISK-edgeOnly"):
                J.append(dict(experiment="backhaul", policy=p, variant=f"badBH,fog={fog}", seed=s,
                              cfg={**BAD_BH, "fog": {"enabled": fog}}))
        for mult in (4, 16):
            for p in ("EDGE-PER", "SOD-PULL", "BRISK", "BRISK-edgeOnly"):
                J.append(dict(experiment="analytics", policy=p, variant=f"map x{mult}", seed=s,
                              cfg={**BAD_BH, "fog": {"enabled": False}, "tasks": {"map_work_s": 15.5 * mult}}))
    for j in J:
        j.setdefault("label", j["policy"])
    return J


if __name__ == "__main__":
    a = cli()
    run_jobs(jobs(a.seeds), a.out or os.path.join(ROOT, "results", "raw", "sensitivity.csv"), a.config, a.procs)
