# Methodology summary

* **Workload.** Six CAF fields (one per year 2010-2015, June-September), 42 nodes each, hourly
  raw readings; QC'd readings are ground truth.  One USCRN station per field (2023, aligned by
  calendar day).  Composite: the sources are not co-located.
* **Links.** Per station of the UWA farm: node-side Gilbert-Elliott chain (packets lost at both
  receivers) + receiver-specific chains, fitted on the common recording period; converted to
  continuous time with q = -ln(1-p)/Delta.
* **Access.** SF9/125 kHz/CR4-5 (UWA PHY), 36-byte frames (267 ms), 8 channels, no capture,
  half-duplex gateway, RX1 1 % / RX2 10 % duty cycles, Class-B beacons/ping slots for Class-B
  policies.
* **Compute.** Edge 1 core x 0.25, fog 4 x 1, cloud 16 x 1 with background utilisation
  0.6 x Azure per-minute shape (cap 0.95).  Preemptive EDF (FIFO for CLOUD-PER).
* **Backhaul.** Two-state (2 Mb/s, 60 ms / 180 kb/s, 180 ms), exponential holding times 4 h / 30 min.
* **Metrics.** Zone-state tracking accuracy (hourly, every zone, both events), hard-case accuracy
  (|true fraction - 0.5| <= 0.15), alarm decision accuracy, COT (correct and on time over all raised
  alarms), urgent latency (sampling instant -> decision at gateway), radio energy per node-day,
  map RMSE, PDR, tier utilisation, controller time.
* **Statistics.** 10 paired seeds (main, trade-off curves), 5 (sensitivity, scalability); tables show
  means; paired Wilcoxon tests, bootstrap CIs and d_z in `results/tables/paired_statistics.csv`.

Every parameter, its unit and provenance tag ([D]/[S]/[L]/[M]/[A]) is listed in
`config/default.yaml` and Table 6 of the paper.
