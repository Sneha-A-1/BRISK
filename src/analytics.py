"""Reference implementations of the computational tasks whose execution time is
profiled to set the task work values (experiments/profile_tasks.py)."""
import numpy as np
from scipy.linalg import cho_factor, cho_solve


def gp_field_map(X: np.ndarray, y: np.ndarray, Xq: np.ndarray, length: float = 0.3,
                 noise: float = 1e-3) -> np.ndarray:
    """Gaussian-process (simple kriging) interpolation of a field-map window.
    X: [n, 3] normalised (easting, northing, time); y: [n]; Xq: [m, 3] query points."""
    d = ((X[:, None, :] - X[None, :, :]) ** 2).sum(-1)
    K = np.exp(-d / (2 * length ** 2)) + noise * np.eye(len(X))
    c = cho_factor(K)
    alpha = cho_solve(c, y - y.mean())
    dq = ((Xq[:, None, :] - X[None, :, :]) ** 2).sum(-1)
    return y.mean() + np.exp(-dq / (2 * length ** 2)) @ alpha


def zone_verification(values: np.ndarray, eps: np.ndarray, theta: np.ndarray, history: np.ndarray,
                      frac: float = 0.5):
    """Interval quorum on the zone members plus a 24-h least-squares trend check of the
    alarming node (history: [24])."""
    lo, hi = values - eps, values + eps
    yes = int((hi < theta).sum())
    unc = int(((lo < theta) & (hi >= theta)).sum())
    n = len(values)
    status = "pos" if yes >= frac * n else ("neg" if yes + unc < frac * n else "inc")
    t = np.arange(len(history))
    slope = np.polyfit(t, history, 1)[0]
    return status, slope
