# Data acquisition

The experiments use five public, non-image datasets. They are **not redistributed** here;
download them and place the files exactly as listed, then run
`python -m src.preprocessing --raw data/raw --out data/processed`.

| Folder | Dataset | Where to get it | Files needed | Licence / terms |
|---|---|---|---|---|
| `data/raw/caf/` | CAF field-scale soil sensor network (USDA ARS / WSU), DOI 10.15482/USDA.ADC/1349683 | Ag Data Commons, `CAF_Sensor_Dataset_2.zip` (https://ndownloader.figshare.com/files/44335805) | unzip the archive here (folders `caf_sensors/Hourly`, `QC/Flags`, `CAF_sensors.shp` ...) | US public domain |
| `data/raw/uwa/` | LoRa Underground Farm Sensor Network (UWA), DOI 10.26182/5d8036e5c4ca7 | https://research-repository.uwa.edu.au/en/datasets/lora-underground-farm-sensor-network/ | `loggerClean.csv`, `Rx2channelClean.csv`, `Rx2measurementClean.csv`, `UWAfarmweatherstation.csv`, `UWAfarm15jul2019_MD.Rmd` | CC BY |
| `data/raw/intel/` | Intel Berkeley Research Lab data | https://db.csail.mit.edu/labdata/labdata.html | `data.txt.gz`, `mote_locs.txt`, `connectivity.txt` | free use, acknowledgement requested |
| `data/raw/uscrn/` | USCRN sub-hourly (5-min) product, NOAA NCEI | https://www.ncei.noaa.gov/pub/data/uscrn/products/subhourly01/2023/ | `CRNS0101-05-2023-{NE_Lincoln_11_SW, IA_Des_Moines_17_E, KS_Manhattan_6_SSW, IL_Champaign_9_SW, CA_Merced_23_WSW, WA_Spokane_17_SSW}.txt` | NOAA public data |
| `data/raw/azure/` | Azure Functions Trace 2019 | https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz | extract the archive here (`invocations_per_function_md.anon.d01..14.csv`, `function_durations_percentiles.anon.d01..14.csv`, ...) | CC BY |

## Verified file characteristics (as received for this study)

* CAF: 42 hourly files, 3,373,658 rows, 4/20/2007-6/16/2016; 890 rows without a timestamp; 46.4 % of
  cells missing after QC.
* UWA: `loggerClean.csv` 163,200 packets (10 Sep 2018 - 2 Jun 2019); `Rx2channelClean.csv` 49,248 rows
  (9 Sep - 5 Dec 2018).  Packet counters (`PktID`) allow loss reconstruction.
* Intel: 2,313,682 readings; 2,917 directed links after removing self-links.
* USCRN: 105,120 five-minute rows per station for 2023; **the 5-cm soil moisture/temperature columns are
  missing for the whole year at all six stations** (only weather variables are used).
* Azure: 20,160 per-minute totals (14 days); 11,422 duration rows with non-positive averages were dropped.

## What is real and what is modelled

Real: soil and weather observations, packet-loss statistics (fitted), the time variation of
cloud load.  Modelled: LoRa air time and energy (datasheet), collisions/half-duplex/duty cycles,
backhaul, compute tiers, thresholds, zones and deadlines.  See `docs/methodology.md`.
