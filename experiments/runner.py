"""Shared experiment runner: executes (policy, config-override, seed) jobs in parallel
worker processes and appends one summary row per run to a CSV in results/raw/.

Each worker loads the processed datasets once (Bundle) and reuses them.
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing as mp
import os
import sys
import time

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.baseline_algorithms import BASELINES  # noqa: E402
from src.proposed_algorithm import ABLATIONS  # noqa: E402

POLICIES = {**BASELINES, **ABLATIONS}

_B = None
_CFG_BASE = None


def deep_update(d: dict, u: dict) -> dict:
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            deep_update(d[k], v)
        else:
            d[k] = v
    return d


def load_cfg(path: str) -> dict:
    with open(os.path.join(ROOT, path) if not os.path.isabs(path) else path) as f:
        cfg = yaml.safe_load(f)
    cfg["data"]["processed_dir"] = os.path.join(ROOT, cfg["data"]["processed_dir"])
    return cfg


def _init(cfg_path):
    global _B, _CFG_BASE
    from src.simulator import Bundle
    _CFG_BASE = load_cfg(cfg_path)
    _B = Bundle(_CFG_BASE)


def _run(job):
    from src.simulator import Simulation
    cfg = deep_update(copy.deepcopy(_CFG_BASE), job.get("cfg", {}))
    pol = dict(POLICIES[job["policy"]])
    pol.update(job.get("pol", {}))
    m = Simulation(cfg, pol, job["seed"], _B, job["policy"]).run()
    row = m.summary()
    row.update({"experiment": job["experiment"], "variant": job.get("variant", ""),
                "label": job.get("label", job["policy"])})
    if job.get("keep_tasks"):
        row["_tasks"] = m.tasks
    return row


def run_jobs(jobs: list, out_csv: str, cfg_path: str = "config/default.yaml", procs: int = 2,
             tasks_dir: str | None = None) -> pd.DataFrame:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    done = set()
    if os.path.exists(out_csv):
        prev = pd.read_csv(out_csv)
        done = set(zip(prev.label, prev.variant.fillna(""), prev.seed))
    todo = [j for j in jobs if (j.get("label", j["policy"]), j.get("variant", ""), j["seed"]) not in done]
    print(f"[runner] {len(jobs)} jobs, {len(todo)} to run -> {out_csv}", flush=True)
    t0 = time.time()
    with mp.Pool(procs, initializer=_init, initargs=(cfg_path,)) as pool:
        for i, row in enumerate(pool.imap_unordered(_run, todo)):
            tasks = row.pop("_tasks", None)
            if tasks is not None and tasks_dir:
                os.makedirs(tasks_dir, exist_ok=True)
                pd.DataFrame(tasks).to_csv(os.path.join(
                    tasks_dir, f"{row['label']}_{row['variant']}_{row['seed']}.csv.gz".replace("/", "_")),
                    index=False)
            df = pd.DataFrame([row])
            df.to_csv(out_csv, mode="a", header=not os.path.exists(out_csv), index=False)
            print(f"[runner] {i + 1}/{len(todo)} {row['label']} {row['variant']} seed={row['seed']} "
                  f"({row['wall_s']:.0f}s, elapsed {time.time() - t0:.0f}s)", flush=True)
    return pd.read_csv(out_csv)


def seeds(n: int, base: int = 1000) -> list:
    return [base + i for i in range(n)]


def cli() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/default.yaml")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--out", default=None)
    return ap.parse_args()
