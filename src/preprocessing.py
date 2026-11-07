"""Preprocessing of the five public datasets used in the study.

Every transformation applied to the raw files is implemented here so that the
processed inputs of the simulator can be regenerated from the original
downloads (see data/README.md for acquisition instructions).

Run:  python -m src.preprocessing --raw data/raw --out data/processed
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np
import pandas as pd

CAF_VARS = [f"VW_{d}cm" for d in (30, 60, 90, 120, 150)] + [
    f"T_{d}cm" for d in (30, 60, 90, 120, 150)
]

USCRN_COLS = [
    "WBANNO", "UTC_DATE", "UTC_TIME", "LST_DATE", "LST_TIME", "CRX_VN", "LONGITUDE",
    "LATITUDE", "AIR_TEMPERATURE", "PRECIPITATION", "SOLAR_RADIATION", "SR_FLAG",
    "SURFACE_TEMPERATURE", "ST_TYPE", "ST_FLAG", "RELATIVE_HUMIDITY", "RH_FLAG",
    "SOIL_MOISTURE_5", "SOIL_TEMPERATURE_5", "WETNESS", "WET_FLAG", "WIND_1_5",
    "WIND_FLAG",
]


# --------------------------------------------------------------------------- CAF
def _read_flags(path: str, var: str) -> pd.DataFrame:
    """Read one CAF QC flag file -> DataFrame(Location, ts) of flagged hours."""
    f = pd.read_csv(path, sep="\t", dtype=str)
    if f.empty:
        return pd.DataFrame(columns=["Location", "ts"])
    f.columns = [c.strip('"') for c in f.columns]
    if "Time" not in f.columns:
        return pd.DataFrame(columns=["Location", "ts"])
    ts = pd.to_datetime(f["Date"] + " " + f["Time"], format="%m/%d/%Y %H:%M", errors="coerce")
    return pd.DataFrame({"Location": f["Location"], "ts": ts}).dropna()


def preprocess_caf(raw: str, out: str, log: dict) -> None:
    import shapefile  # pyshp

    files = sorted(glob.glob(os.path.join(raw, "caf", "caf_sensors", "Hourly", "*.txt")))
    frames = []
    for fp in files:
        d = pd.read_csv(fp, sep="\t", na_values=["NA"])
        d["ts"] = pd.to_datetime(d["Date"] + " " + d["Time"], format="%m/%d/%Y %H:%M")
        frames.append(d[["Location", "ts"] + CAF_VARS])
    caf = pd.concat(frames, ignore_index=True)
    n_rows = len(caf)
    n_bad_ts = int(caf.ts.isna().sum())
    caf = caf.dropna(subset=["ts"])
    dup = int(caf.duplicated(["Location", "ts"]).sum())
    caf = caf.drop_duplicates(["Location", "ts"])
    na_before = caf[CAF_VARS].isna().sum().sum()

    # QC 1: physical range (dataset README: VW in [0, 0.6] m3/m3)
    for c in CAF_VARS[:5]:
        bad = (caf[c] < 0) | (caf[c] > 0.6)
        caf.loc[bad, c] = np.nan
    # QC 2: spikes and breaks flagged by the dataset authors (Dorigo et al. 2013 rules)
    masked_flags = 0
    for kind in ("spikes", "breaks"):
        for d in (30, 60, 90, 120, 150):
            fp = os.path.join(raw, "caf", "QC", "Flags", f"{kind}VW_{d}.txt")
            if not os.path.exists(fp):
                continue
            fl = _read_flags(fp, f"VW_{d}cm")
            if fl.empty:
                continue
            key = caf.set_index(["Location", "ts"]).index
            hit = key.isin(pd.MultiIndex.from_frame(fl))
            masked_flags += int((hit & caf[f"VW_{d}cm"].notna().to_numpy()).sum())
            caf.loc[hit, f"VW_{d}cm"] = np.nan
    na_after = caf[CAF_VARS].isna().sum().sum()

    caf = caf.sort_values(["Location", "ts"])
    caf.to_csv(os.path.join(out, "caf_hourly.csv.gz"), index=False, float_format="%.4f")

    # Dense cubes [location, hour, channel] used by the simulator.  'raw' is what a
    # sensor node would emit (original values, including faults); 'qc' is the
    # quality-controlled reference used as ground truth.
    raw_frames = []
    for fp in files:
        d = pd.read_csv(fp, sep="\t", na_values=["NA"])
        d["ts"] = pd.to_datetime(d["Date"] + " " + d["Time"], format="%m/%d/%Y %H:%M")
        raw_frames.append(d[["Location", "ts"] + CAF_VARS])
    raw_df = pd.concat(raw_frames).dropna(subset=["ts"]).drop_duplicates(["Location", "ts"])
    locs = sorted(caf.Location.unique())
    t0 = caf.ts.min().floor("D")
    n_h = int((caf.ts.max() - t0) / pd.Timedelta(hours=1)) + 1
    cubes = {}
    for name, df in (("raw", raw_df), ("qc", caf)):
        cube = np.full((len(locs), n_h, len(CAF_VARS)), np.nan, dtype=np.float32)
        li = df.Location.map({l: i for i, l in enumerate(locs)}).to_numpy()
        hi = ((df.ts - t0) / pd.Timedelta(hours=1)).to_numpy().astype(int)
        cube[li, hi, :] = df[CAF_VARS].to_numpy(dtype=np.float32)
        cubes[name] = cube
    np.savez_compressed(os.path.join(out, "caf_cube.npz"), raw=cubes["raw"], qc=cubes["qc"],
                        locations=np.array(locs), t0=str(t0), channels=np.array(CAF_VARS))

    r = shapefile.Reader(os.path.join(raw, "caf", "CAF_sensors.shp"))
    loc = pd.DataFrame([rec[:3] for rec in r.records()], columns=["Location", "Easting", "Northing"])
    loc.to_csv(os.path.join(out, "caf_locations.csv"), index=False)

    cov = caf.assign(year=caf.ts.dt.year).groupby("year")[CAF_VARS[0]].apply(lambda s: s.notna().mean())
    log["caf"] = {
        "files": len(files),
        "rows_raw": n_rows,
        "rows_without_timestamp_removed": n_bad_ts,
        "duplicate_rows_removed": dup,
        "missing_cells_raw": int(na_before),
        "cells_masked_by_qc": int(na_after - na_before),
        "spike_break_flags_applied": masked_flags,
        "missing_fraction_after_qc": round(float(caf[CAF_VARS].isna().mean().mean()), 4),
        "vw30_coverage_by_year": {int(k): round(float(v), 3) for k, v in cov.items()},
        "locations": int(loc.shape[0]),
    }


# ------------------------------------------------------------------------- USCRN
def preprocess_uscrn(raw: str, out: str, log: dict) -> None:
    rows = {}
    frames = []
    for fp in sorted(glob.glob(os.path.join(raw, "uscrn", "CRNS0101-05-*.txt"))):
        name = os.path.basename(fp).split("-", 3)[3][:-4]
        d = pd.read_csv(fp, sep=r"\s+", header=None, names=USCRN_COLS, dtype={"CRX_VN": str,
                        "UTC_DATE": str, "UTC_TIME": str})
        d["ts"] = pd.to_datetime(d.UTC_DATE + d.UTC_TIME.str.zfill(4), format="%Y%m%d%H%M")
        keep = ["AIR_TEMPERATURE", "PRECIPITATION", "SOLAR_RADIATION", "RELATIVE_HUMIDITY",
                "WIND_1_5", "SURFACE_TEMPERATURE", "SOIL_MOISTURE_5"]
        d = d[["ts"] + keep].copy()
        for c in keep:  # README note C: missing = lowest value for the field format
            d.loc[d[c] <= -99.0, c] = np.nan
        d["station"] = name
        rows[name] = {
            "rows": len(d),
            "missing": {c: round(float(d[c].isna().mean()), 4) for c in keep},
        }
        frames.append(d)
    u = pd.concat(frames, ignore_index=True)
    u.drop(columns=["SOIL_MOISTURE_5"]).to_csv(
        os.path.join(out, "uscrn_5min.csv.gz"), index=False, float_format="%.3f")
    log["uscrn"] = rows


# --------------------------------------------------------------------------- UWA
def _gilbert_elliott(received_seq: np.ndarray) -> dict:
    """Fit a two-state (Gilbert-Elliott, loss = bad state) Markov chain to a 0/1
    reception sequence (1 = received).  Returns transition probabilities."""
    x = received_seq.astype(int)
    a, b = x[:-1], x[1:]
    p_gb = ((a == 1) & (b == 0)).sum() / max((a == 1).sum(), 1)  # good -> loss
    p_bg = ((a == 0) & (b == 1)).sum() / max((a == 0).sum(), 1)  # loss -> good
    return {"p_good_to_bad": float(p_gb), "p_bad_to_good": float(p_bg)}


def preprocess_uwa(raw: str, out: str, log: dict) -> None:
    L = pd.read_csv(os.path.join(raw, "uwa", "loggerClean.csv"))
    L["ts"] = pd.to_datetime(L.Timestamp.astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    L = L.rename(columns={"SensorID": "station", "SignalToNoiseRatio": "snr", "RealRSSI": "rssi"})
    L = L.dropna(subset=["ts"]).sort_values(["station", "ts"])
    n_raw = len(L)
    L = L.drop_duplicates(["station", "PktID", "ts"])
    stats, seq_rows, link_rows = {}, [], []
    for st, g in L.groupby("station"):
        pk = g.PktID.to_numpy()
        # A node reset (metadata: node 4 reset 2018-10-10) or 16-bit wrap makes the
        # counter jump backwards; a forward jump > 1000 is treated as a reset too.
        d = np.diff(pk)
        segs = np.split(np.arange(len(pk)), np.where((d <= 0) | (d > 1000))[0] + 1)
        expected = received = 0
        seq_rows = []
        for s in segs:
            if len(s) < 2:
                continue
            p = pk[s]
            expected += int(p[-1] - p[0] + 1)
            received += len(np.unique(p))
            rx = np.zeros(int(p[-1] - p[0] + 1), dtype=bool)
            rx[(p - p[0]).astype(int)] = True
            seq_rows.append(rx)
        rx_all = np.concatenate(seq_rows) if seq_rows else np.array([1])
        ge = _gilbert_elliott(rx_all)
        iat = g.ts.diff().dt.total_seconds().dropna()
        stats[int(st)] = {
            "packets_received": int(received),
            "packets_expected": int(expected),
            "pdr": round(received / expected, 4),
            "median_report_interval_s": float(iat.median()),
            "rssi_median_dbm": float(g.rssi.median()),
            "snr_median_db": float(g.snr.median()),
            "snr_p05_db": float(g.snr.quantile(0.05)),
            "battery_v_median": float(g.BatteryV.median()),
            **{k: round(v, 4) for k, v in ge.items()},
        }
        link_rows.append(g[["station", "ts", "PktID", "rssi", "snr", "NoiseFloor", "BatteryV"]])
    pd.concat(link_rows).to_csv(os.path.join(out, "uwa_link_records.csv.gz"), index=False)
    # Empirical SNR -> per-packet reception relation (SNR is only observed for
    # received packets, so we report the per-station SNR distribution, not a PER curve)
    log["uwa"] = {"records_raw": n_raw, "records_dedup": len(L), "stations": stats,
                  "lora": {"sf": 9, "bw_hz": 125000, "cr": "4/5", "tx_dbm": 20, "f_mhz": 174,
                           "source": "UWAfarm15jul2019_MD (dataset metadata)"}}
    with open(os.path.join(out, "uwa_link_params.json"), "w") as f:
        json.dump(stats, f, indent=1)


def preprocess_uwa_diversity(raw: str, out: str, log: dict) -> None:
    """Decompose LoRa losses into a node-side component (packet lost at BOTH receivers)
    and receiver-specific components, using the period in which both UWA receivers
    (logger and Raspberry-Pi 'Rx2') were recording (Sep-Dec 2018).  Each component is
    fitted as a Gilbert-Elliott chain on the packet-counter sequence; receiver-specific
    chains are fitted on the sub-sequence of packets that survived the node-side
    component."""
    L = pd.read_csv(os.path.join(raw, "uwa", "loggerClean.csv"))
    L["ts"] = pd.to_datetime(L.Timestamp.astype(str), format="%Y%m%d%H%M%S", errors="coerce")
    C = pd.read_csv(os.path.join(raw, "uwa", "Rx2channelClean.csv"))
    C["ts"] = pd.to_datetime(C.timestampStr, errors="coerce").dt.tz_localize(None)
    C = C.dropna(subset=["StationID"])
    t0, t1 = max(L.ts.min(), C.ts.min()), min(L.ts.max(), C.ts.max())
    res = {}
    for st in range(1, 6):
        a = L[(L.SensorID == st) & L.ts.between(t0, t1)].sort_values("ts")
        b = C[(C.StationID == st) & C.ts.between(t0, t1)].sort_values("ts")
        ids_a, ids_b = set(a.PktID.astype(int)), set(b.PktID.astype(int))
        allids = np.array(sorted(ids_a | ids_b))
        # split into contiguous counter segments (resets / long outages > 1000 ids)
        cuts = np.where(np.diff(allids) > 1000)[0] + 1
        r1, r2 = [], []
        for seg in np.split(allids, cuts):
            if len(seg) < 50:
                continue
            rng_ids = np.arange(seg[0], seg[-1] + 1)
            r1.append(np.isin(rng_ids, list(ids_a)))
            r2.append(np.isin(rng_ids, list(ids_b)))
        r1, r2 = np.concatenate(r1), np.concatenate(r2)
        common_ok = r1 | r2
        ge_c = _gilbert_elliott(common_ok)
        ge_1 = _gilbert_elliott(r1[common_ok])
        ge_2 = _gilbert_elliott(r2[common_ok])
        iat = a.ts.diff().dt.total_seconds().median()
        res[st] = {"n": int(len(r1)), "pdr_rx1": round(float(r1.mean()), 4),
                   "pdr_rx2": round(float(r2.mean()), 4),
                   "pdr_union": round(float(common_ok.mean()), 4),
                   "pdr_union_if_independent": round(float(1 - (1 - r1.mean()) * (1 - r2.mean())), 4),
                   "node_side": ge_c, "rx1": ge_1, "rx2": ge_2,
                   "interval_s": float(iat)}
    with open(os.path.join(out, "uwa_diversity_params.json"), "w") as f:
        json.dump(res, f, indent=1)
    log["uwa_diversity"] = {"window": [str(t0), str(t1)], "stations": res}


# ------------------------------------------------------------------------- Intel
def preprocess_intel(raw: str, out: str, log: dict) -> None:
    loc = pd.read_csv(os.path.join(raw, "intel", "mote_locs.txt"), sep=r"\s+", header=None,
                      names=["mote", "x", "y"])
    con = pd.read_csv(os.path.join(raw, "intel", "connectivity.txt"), sep=r"\s+", header=None,
                      names=["sender", "receiver", "p"])
    con = con[(con.sender != con.receiver)]
    valid = set(loc.mote) | {0}
    con = con[con.sender.isin(valid) & con.receiver.isin(valid)]
    loc.to_csv(os.path.join(out, "intel_locations.csv"), index=False)
    con.to_csv(os.path.join(out, "intel_links.csv"), index=False)
    d = pd.read_csv(os.path.join(raw, "intel", "data.txt.gz"), sep=r"\s+", header=None,
                    names=["date", "time", "epoch", "moteid", "temp", "hum", "light", "volt"],
                    on_bad_lines="skip")
    n_raw = len(d)
    d = d[d.moteid.isin(loc.mote)]
    epochs = d.epoch.max() - d.epoch.min() + 1
    yield_per_mote = d.groupby("moteid").epoch.nunique() / epochs
    log["intel"] = {
        "readings_raw": int(n_raw),
        "readings_valid_mote": int(len(d)),
        "motes": int(loc.shape[0]),
        "directed_links": int(len(con)),
        "links_p_gt_0_5": int((con.p > 0.5).sum()),
        "mean_link_p_nonzero": round(float(con.p[con.p > 0].mean()), 4),
        "median_epoch_yield_per_mote": round(float(yield_per_mote.median()), 4),
    }


# ------------------------------------------------------------------------- Azure
def preprocess_azure(raw: str, out: str, log: dict) -> None:
    base = os.path.join(raw, "azure")
    minute_series = []
    for i in range(1, 15):
        fp = os.path.join(base, f"invocations_per_function_md.anon.d{i:02d}.csv")
        tot = None
        for chunk in pd.read_csv(fp, chunksize=10000):
            s = chunk.iloc[:, 4:].sum(axis=0).to_numpy(dtype=np.float64)
            tot = s if tot is None else tot + s
        minute_series.append(tot)
    series = np.concatenate(minute_series)
    pd.DataFrame({"minute": np.arange(len(series)), "invocations": series.astype(np.int64)}).to_csv(
        os.path.join(out, "azure_minute_load.csv.gz"), index=False)

    # Execution-time distribution: per-function average duration (ms), weighted by
    # invocation count; non-positive averages (present in the raw files) are dropped.
    durs = []
    bad = 0
    for i in range(1, 15):
        d = pd.read_csv(os.path.join(base, f"function_durations_percentiles.anon.d{i:02d}.csv"),
                        usecols=["HashFunction", "Average", "Count"])
        bad += int((d.Average <= 0).sum())
        durs.append(d[d.Average > 0])
    du = pd.concat(durs)
    w = du.Count.to_numpy(float)
    order = np.argsort(du.Average.to_numpy())
    vals = du.Average.to_numpy()[order]
    cdf = np.cumsum(w[order]) / w.sum()
    qs = np.linspace(0.001, 0.999, 999)
    qv = np.interp(qs, cdf, vals)
    pd.DataFrame({"q": qs, "duration_ms": qv}).to_csv(os.path.join(out, "azure_duration_quantiles.csv"),
                                                      index=False)
    log["azure"] = {
        "minutes": int(len(series)),
        "invocations_total": int(series.sum()),
        "per_minute_min_median_max": [int(series.min()), int(np.median(series)), int(series.max())],
        "peak_to_median": round(float(series.max() / np.median(series)), 3),
        "duration_rows": int(len(du)),
        "nonpositive_duration_rows_removed": bad,
        "weighted_duration_ms_p50_p90_p99": [round(float(np.interp(q, cdf, vals)), 1) for q in (0.5, 0.9, 0.99)],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/processed")
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    logp = os.path.join(a.out, "preprocessing_log.json")
    log = json.load(open(logp)) if os.path.exists(logp) else {}
    steps = {"caf": preprocess_caf, "uscrn": preprocess_uscrn, "uwa": preprocess_uwa,
             "uwa_div": preprocess_uwa_diversity,
             "intel": preprocess_intel, "azure": preprocess_azure}
    for k, fn in steps.items():
        if a.only and k not in a.only:
            continue
        print(f"[preprocess] {k}", flush=True)
        fn(a.raw, a.out, log)
        json.dump(log, open(logp, "w"), indent=1)
    print(json.dumps(log, indent=1))


if __name__ == "__main__":
    main()
