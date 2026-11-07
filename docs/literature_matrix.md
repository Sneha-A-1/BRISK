# Literature matrix, research gaps and journal fit

All entries below were verified against a publisher page, a Crossref DOI record, or an
official dataset page (see `reference_verification.md`).  "Stated limitation" = written
by the authors; "Our analysis" = our own technical reading.  We do not infer that a
method fails because a metric is not reported.

## 1. Journal fit (Stage 1)

* **Why TOSN.** TOSN publishes systemic sensor-network research.  The problem studied here
  is a sensor-network problem first: what a battery-powered LoRa network should transmit,
  how a gateway should reason about the bounded uncertainty that suppression and bursty
  losses leave, and how this couples with where decisions are computed.  Recent TOSN papers
  address neighbouring questions: useful-information freshness in edge-assisted EH sensor
  networks (Shi et al., TOSN 20(2), 2024), carrier-sense MAC for LoRa (Gamage et al., TOSN
  19(2), 2023), deadline-constrained DAG scheduling on edge servers (Li et al., TOSN 20(1),
  2023), flow-time minimisation for timely stream processing (Xu et al., TOSN 20(3), 2024).
* **Gap.** Agricultural edge-fog-cloud frameworks optimise placement of a given data
  stream; data-reduction schemes adapt tolerances to data statistics; neither uses the
  proximity of readings to actuation thresholds to allocate retrieval effort, nor exploits
  the suppression error bounds at the gateway under bursty, partly undetectable losses.
* **Distinguishing contribution.** Decision-proximity heartbeat/tolerance control coupled
  with a loss-aware interval quorum and deadline-aware placement, plus trace-derived
  insights (heartbeat dominance; node- vs receiver-side loss decomposition).
* **Convincing experiments.** Paired multi-seed comparison on real soil data with real
  loss statistics; whole energy-accuracy trade-off curves; ablations; sensitivity to
  deadlines, burstiness, gateways, backhaul and load; scalability to 1,008 nodes.

## 2. Matrix

| Reference | Research problem | Architecture | Retrieval / data method | Scheduling / decision | Network considerations | Evaluation | Reported metrics | Limitations (stated / our analysis) | Relevance |
|---|---|---|---|---|---|---|---|---|---|
| Vasisht et al., NSDI 2017 (FarmBeats) | End-to-end farm IoT platform | sensors/drones - base station - cloud | not detailed in reviewed summary | -- | design accounts for weather-induced power and Internet outages | two farm deployments, 6 months | (not extracted) | Our analysis: not a retrieval/scheduling study | Motivation: connectivity outages are real |
| Alharbi & Aldossary, IEEE Access 2021 | Energy-efficient edge-fog-cloud for smart agriculture | edge-fog-cloud | processing near sensors | MILP + heuristic placement | network traffic | simulation, thousands of sensors | energy -36 %, emissions -43 %, traffic up to -86 % vs cloud | Our analysis: data stream taken as given; no link losses or deadlines in the summary we reviewed | Cloud-centric baseline concept |
| Zhang et al., SPE 2021 (SOP) | Edge-server placement on farms | sensors - edge servers | -- | candidate layout selection | sensor-to-server delay, load balance | simulation | (no numbers on abstract page) | -- | Placement in farms |
| Baghrous et al., IJECE 2023 | Module placement for fog-based farming apps | fog | -- | placement algorithm | delay, network usage | iFogSim | reductions vs baseline (numbers in PDF) | Our analysis: simulator-only, no radio model | Fog placement prior art |
| Zhang et al., Agronomy 2025 | LoRa + edge irrigation controller | nodes - edge gateway - cloud | periodic polling | rule-based ET/soil-water-balance on gateway | range 4 km, 21 % loss at 4 km/10.9 kbps | field trial, 3 weeks, 2 plots | moisture after irrigation, ET0 correlation | Stated: short trial, sunny-only comm. tests; no cloud-only latency comparison | Real LoRa-edge irrigation system |
| Gong et al., Sensors 2025 (review) | Edge computing in agriculture | review | -- | -- | dead zones, soil dielectric changes, congestion | literature | -- | Stated: priority-aware data handling and energy saving still exploratory | Gap evidence |
| Shi et al., TOSN 2024 | Fresh and useful data in edge-assisted EH-WSN | sensors - edge | AoUI metric | approximation algorithms for Min-AoUI (NP-hard) | energy harvesting | analysis + experiments | AoUI | Our analysis: usefulness not tied to actuation thresholds or zone decisions | Closest TOSN freshness work |
| Jiang et al., IoT-J 2023 | AoI-based offloading + transmission scheduling | devices - MEC | -- | DDPG + D3QN | 2-state channel, slot capacity | simulation | reward, AoI, success share | Stated/evident: one-slot tasks, 2-state channel, simulation only; a baseline wins on reward | Coupled offloading + transmission |
| Li et al., TOSN 2023 | DAG scheduling with deadlines on edge | edge servers + cloud | -- | DP (FixDoc/GenDoc) + online OnDoc | transfer delay | Alibaba trace | completion time, deadline satisfaction | -- | Deadline-aware placement prior art |
| Xu et al., TOSN 2024 | Timely stream processing in UAV MEC | UAV edge | -- | online algorithm, competitive ratio | resource/energy limits | simulation | flow time -19 % | -- | Timeliness in TOSN |
| Gamage et al., TOSN 2023 (LMAC) | LoRa media access | LoRa star | -- | CSMA variants | collisions, channel/SF load | 50-node + 16-node testbeds | goodput x2.2, energy/frame /2.4 | -- | LoRa access realism |
| Asteriou et al., Sensors 2024 | Correlated event bursts in LoRaWAN | LoRaWAN | event reports | learning-automaton TDMA after events | collisions | in-house DES | frame loss, delay (-30 % vs CN) | Evident: single gateway, wake-up receivers assumed | Urgent event traffic in LoRa |
| Zhang, Na, Zhang, Sensors 2023 | Adaptive data reduction | sensor - remote | Kalman prediction, CUSUM-adaptive threshold | -- | transmission rate | Intel Lab + 2 traces | DRR, reconstruction accuracy (+11.7 % / +17.3 %) | Stated/evident: hand-tuned parameters, 3 datasets | Data-driven tolerance adaptation (contrast) |
| Santini & Roemer, INSS 2006; Dias et al. 2016 (survey) | Prediction-based data reduction | WSN | dual prediction | -- | -- | -- | -- | -- | Send-on-delta baseline |
| Hardie & Hoyle, Sensors 2019; Cardell-Oliver et al. 2019 (dataset) | Underground LoRa for agriculture | LoRa | -- | -- | underground attenuation | field data | RSSI/SNR, delivery | -- | Real link data used here |
| Bor et al. 2016; Georgiou & Raza 2017; Adelantado et al. 2017 | LoRa scalability limits | LoRa | -- | ALOHA | collisions, duty cycle | analysis/simulation | capacity, PDR | -- | Access-layer model |
| Alsadie, PeerJ CS 2024 (review) | Heuristic fog-cloud IoT scheduling | fog-cloud | -- | heuristics | dynamics | literature | -- | Stated: simulation-heavy, little scalability analysis | Motivates scalability study |

## 3. Candidate gaps and selection

| Gap | Evidence | Feasible with public data? | TOSN relevance | Selected |
|---|---|---|---|---|
| G1 Retrieval effort is set by data statistics, not by decision relevance; gateways do not exploit suppression error bounds | data-reduction literature adapts thresholds to drift/reconstruction error; agri frameworks take the stream as given | yes (CAF + UWA) | high | **yes (core)** |
| G2 Urgent agricultural traffic under bursty, partly node-side LoRa losses is not characterised | no reviewed agri framework separates node- and receiver-side loss | yes (UWA two receivers) | high | **yes (characterisation + negative result)** |
| G3 Placement of agricultural tasks evaluated with real cloud-load dynamics and rural backhaul | most placement studies use synthetic loads or iFogSim | partly (Azure shape only) | medium | yes (secondary) |
| G4 Learning-based joint scheduling | many DRL works exist | yes | medium | no (urgent compute load is tiny; placement is not the bottleneck) |

## 4. Gap-to-contribution matrix

| Confirmed limitation | Mechanism | Hypothesis tested |
|---|---|---|
| Heartbeats dominate suppression energy (measured, F1) | C1 proximity heartbeat | H1: at equal energy BRISK has lower zone-tracking error than fixed-heartbeat SOD (trade-off curves) |
| Decisions only flip near thresholds (F2) | C1 proximity tolerance, C4 interval quorum | H2: hard-case accuracy improves at equal energy |
| Suppressed vs lost is ambiguous at the gateway (F3) | C3 loss-aware validity | H3: ablation -C3 changes conclusive/certified rate without hurting accuracy |
| Node-side outages last hours (F2 of Sec. 6.1) | C2 deadline-spanning retries | H4: tested; expected small effect for minute-scale deadlines |
| Class-B pulls give context at high energy | BRISK+Watch (scoped Class B) | H5: scoped Class B recovers part of the pull benefit at lower energy |
| Backhaul/cloud variability | C5 slack-aware placement | H6: under degraded backhaul, urgent latency and map deadlines are protected |
