"""Measure the execution time of the task kernels on the reference machine.
Writes results/logs/task_profiling.json.  Run on an otherwise idle machine:
    python experiments/profile_tasks.py
"""
import json
import os
import platform
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.analytics import gp_field_map, zone_verification  # noqa: E402


def timeit(fn, reps):
    ts = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return float(np.median(ts)), [float(x) for x in ts]


def main():
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    rng = np.random.default_rng(0)
    n = 24 * 210  # 24 h x 210 VW channels of one field
    X = rng.random((n, 3)); y = rng.random(n); Xq = rng.random((210, 3))
    map_med, map_all = timeit(lambda: gp_field_map(X, y, Xq), 3)
    v = rng.random(7) * 0.3; e = np.full(7, 0.005); th = np.full(7, 0.15); hist = rng.random(24)
    ver_med, _ = timeit(lambda: zone_verification(v, e, th, hist), 2000)
    out = {"machine": platform.processor() or platform.machine(), "python": platform.python_version(),
           "numpy": np.__version__, "map_gp_5040pts_s_median": map_med, "map_runs_s": map_all,
           "zone_verification_s_median": ver_med}
    os.makedirs(os.path.join(ROOT, "results", "logs"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "logs", "task_profiling.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
