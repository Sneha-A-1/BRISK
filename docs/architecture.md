# Architecture

Editable diagram sources are in `figures/source/` (`architecture.dot`, `dataflow.dot`,
`seq_urgent.mmd`, `seq_strategic.mmd`); rendered PDFs are in `paper/figures/` and SVGs in
`figures/generated/`.  Re-render with

    dot -Tpdf figures/source/architecture.dot -o paper/figures/architecture.pdf
    mmdc -p figures/source/puppeteer.json -i figures/source/seq_urgent.mmd -o paper/figures/seq_urgent.pdf --pdfFit

| Layer | Component | Code | BRISK component |
|---|---|---|---|
| L1 Sensing | soil node: range filter, local alarm, send-on-delta + heartbeat, energy queue | `simulator._on_sample`, `retrieval.tolerance`, `simulator._heartbeat` | C1, C6 |
| L1 Sensing | weather station (5 min), frost / heavy-rain alarms | `simulator._on_wsample` | -- |
| L2 Access | LoRa air time, channels, collisions, half-duplex, duty cycles, node/receiver-side loss chains, retries | `network_model`, `simulator._on_uplink_end`, `simulator._retry_delay` | C2 |
| L3 Gateway | bounded-error replica, sequence gaps, interval quorum, placement, edge CPU | `retrieval.Replica`, `retrieval.classify_member`, `resource_scheduler.place_task` | C3, C4, C5 |
| L4 Fog | 4-core server on a LAN | `resource_scheduler.Tier`, `network_model.LocalLink` | -- |
| L5 Cloud | 16 cores with Azure-shaped background load, archive, analytics | `resource_scheduler.AzureBackground`, `network_model.Backhaul` | -- |
| L6 Services | zone actuation decisions, alerts, hourly maps | `metrics` | -- |

Design assumptions: single-hop LoRa star; time-synchronised nodes; thresholds/zones configured;
gateways forward everything and the network server de-duplicates; no downlink is required
for any BRISK retrieval decision (ACKs only).
