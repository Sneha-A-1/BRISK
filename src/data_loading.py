"""Builds the trace-driven scenario from the processed public datasets.

Field tiles.  The CAF field (42 instrumented locations) is replicated into K
'virtual fields' (tiles) served by one gateway.  Tile k replays a *different time
window* of the real CAF record (growing season of year Y_k, shifted by k//6 weeks),
so every tile carries real, non-duplicated observations.  Each tile is paired with
one USCRN station (5-min weather) aligned by calendar day (2023 record).  The pairing
is a composite workload: CAF (Washington State, 2011-2016) and USCRN (2023) are not
co-located; this is stated as a limitation.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

VW30, T30 = 0, 5  # channel indices in the CAF cube


@dataclass
class FieldData:
    raw: np.ndarray        # [loc, hour, 10] sensor-emitted values (faults present)
    qc: np.ndarray         # [loc, hour, 10] quality-controlled reference (ground truth)
    t0: pd.Timestamp
    locations: list
    xy: np.ndarray         # [loc, 2] UTM coordinates (m)
    theta_dry: np.ndarray  # [loc] refill threshold on VW_30 (m3/m3)
    theta_wet: np.ndarray  # [loc] saturation threshold on VW_30
    zones: np.ndarray      # [loc] management-zone id


def _kmeans(xy: np.ndarray, k: int, seed: int = 0, iters: int = 100) -> np.ndarray:
    rng = np.random.default_rng(seed)
    c = xy[rng.choice(len(xy), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((xy[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([xy[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
        if np.allclose(new, c):
            break
        c = new
    return lab


def load_field(proc: str, cfg: dict) -> FieldData:
    z = np.load(os.path.join(proc, "caf_cube.npz"), allow_pickle=False)
    raw, qc = z["raw"], z["qc"]
    t0 = pd.Timestamp(str(z["t0"]))
    locs = [str(s) for s in z["locations"]]
    loc = pd.read_csv(os.path.join(proc, "caf_locations.csv")).set_index("Location").loc[locs]
    xy = loc[["Easting", "Northing"]].to_numpy(float)
    # thresholds from the QC'd growing-season record of each location
    hours = t0 + pd.to_timedelta(np.arange(qc.shape[1]), unit="h")
    season = np.isin(hours.month, list(range(cfg["season"]["months"][0], cfg["season"]["months"][1] + 1)))
    vw = qc[:, season, VW30]
    theta_dry = np.nanquantile(vw, cfg["events"]["dry_quantile"], axis=1)
    theta_wet = np.nanquantile(vw, cfg["events"]["wet_quantile"], axis=1)
    zones = _kmeans(xy, cfg["zones_per_tile"], seed=cfg["zone_seed"])
    return FieldData(raw, qc, t0, locs, xy, theta_dry.astype(float), theta_wet.astype(float), zones)


def tile_start_hours(fd: FieldData, cfg: dict, n_tiles: int) -> list:
    """Hour index (into the cube) at which each tile's replay starts."""
    out = []
    years = cfg["tile_years"]
    for k in range(n_tiles):
        y = years[k % len(years)]
        start = pd.Timestamp(f"{y}-{cfg['season']['start_mmdd']}") + pd.Timedelta(
            days=cfg["tile_offset_days"] * (k // len(years)))
        out.append(int((start - fd.t0) / pd.Timedelta(hours=1)))
    return out


@dataclass
class WeatherData:
    names: list
    t_air: np.ndarray   # [station, 5-min index] for 2023
    precip: np.ndarray
    t_surf: np.ndarray
    t0: pd.Timestamp


def load_weather(proc: str) -> WeatherData:
    u = pd.read_csv(os.path.join(proc, "uscrn_5min.csv.gz"), parse_dates=["ts"])
    names = sorted(u.station.unique())
    t0 = pd.Timestamp("2023-01-01 00:05")
    n = 365 * 288
    arr = {k: np.full((len(names), n), np.nan, np.float32) for k in ("AIR_TEMPERATURE", "PRECIPITATION",
                                                                    "SURFACE_TEMPERATURE")}
    for i, s in enumerate(names):
        d = u[u.station == s]
        idx = ((d.ts - t0) / pd.Timedelta(minutes=5)).to_numpy().astype(int)
        ok = (idx >= 0) & (idx < n)
        for k in arr:
            arr[k][i, idx[ok]] = d[k].to_numpy(np.float32)[ok]
    return WeatherData(names, arr["AIR_TEMPERATURE"], arr["PRECIPITATION"], arr["SURFACE_TEMPERATURE"], t0)


def load_links(proc: str) -> dict:
    with open(os.path.join(proc, "uwa_link_params.json")) as f:
        return {int(k): v for k, v in json.load(f).items()}


def load_azure(proc: str) -> np.ndarray:
    return pd.read_csv(os.path.join(proc, "azure_minute_load.csv.gz")).invocations.to_numpy(float)
