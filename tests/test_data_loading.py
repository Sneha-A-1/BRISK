import os

import numpy as np
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
needs_data = pytest.mark.skipif(not os.path.exists(os.path.join(PROC, "caf_cube.npz")),
                                reason="processed data not present (run src/preprocessing.py)")


@needs_data
def test_field_cube_and_thresholds():
    from src import data_loading as DL
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config", "default.yaml")))
    fd = DL.load_field(PROC, cfg)
    assert fd.raw.shape == fd.qc.shape and fd.raw.shape[0] == 42 and fd.raw.shape[2] == 10
    assert np.all(fd.theta_dry < fd.theta_wet)
    assert len(set(fd.zones)) == cfg["zones_per_tile"]
    # QC'd moisture is within the physical range enforced by the QC rules
    vw = fd.qc[:, :, :5]
    assert np.nanmin(vw) >= 0 and np.nanmax(vw) <= 0.6
    starts = DL.tile_start_hours(fd, cfg, cfg["tiles"])
    assert all(s + cfg["horizon_hours"] <= fd.raw.shape[1] for s in starts)


@needs_data
def test_link_parameters_are_probabilities():
    import json
    d = json.load(open(os.path.join(PROC, "uwa_diversity_params.json")))
    for st in d.values():
        for comp in ("node_side", "rx1", "rx2"):
            for v in st[comp].values():
                assert 0.0 <= v <= 1.0
        assert st["pdr_union"] >= max(st["pdr_rx1"], st["pdr_rx2"]) - 1e-9
