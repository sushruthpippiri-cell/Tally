# Benchmark run — TEMPLATE

Copy this to `docs/benchmarks/perf-val-<date>.md` and fill in **every** field.

**PERF-VAL-1 is a validity rule, not a wish list:** a benchmark result is valid evidence *only
if* it records all of these. A run missing any field is not evidence, and the acceptance report
will say so. That is why the fields are listed before the numbers — fill the top half in first,
while you are at the machine.

PERF-VAL-2 is worth reading with it: these are repeatable benchmark conditions, **not a
guarantee for every customer environment**. Do not quote them to a customer as what their PC
will do.

---

## 1. The machine running TallyPrime and the Agent (PERF-VAL-1)

| Field | Value | How to get it |
|---|---|---|
| Windows edition and build | | `winver`, or `Get-ComputerInfo \| Select WindowsProductName, WindowsVersion, OsBuildNumber` |
| CPU model | | `Get-CimInstance Win32_Processor \| Select Name, NumberOfCores` |
| RAM | | `Get-CimInstance Win32_ComputerSystem \| Select TotalPhysicalMemory` |
| Storage type (SSD / NVMe / HDD) | | `Get-PhysicalDisk \| Select FriendlyName, MediaType, Size` |
| Free space on the Tally volume | | `Get-Volume` |
| x64 or ARM | | `$env:PROCESSOR_ARCHITECTURE` — **must be AMD64** (D-043 #3; an ARM VM under emulation is not valid evidence) |
| TallyPrime version and build | | Help → About in TallyPrime; record both |
| Agent version | | `tally-agent.exe --version` |
| Agent configuration | | `extraction_batch_size`, `tally_host`/`tally_port`, any `--proxy-url` or `--ca-bundle`; paste the non-secret part of `agent.toml` |

## 2. The dataset

| Field | Value |
|---|---|
| Dataset identifier | |
| Vouchers / entries / ledgers / stock items | |
| Financial years covered | |
| Real company or generated | |

The SRS 17.2 dataset is 100,000 vouchers, 500,000 entries, 5,000 ledgers and 10,000 stock items.
If the run used a real company, say so and give its sizes — a smaller dataset is still useful,
but it is not a 17.2 run and the report must not claim it is.

## 3. The network, measured during the run (PERF-VAL-1)

Not from the broadband contract: **measured**, while the sync was happening, because that is
what the sync competed with.

| Field | Value | How |
|---|---|---|
| Downstream / upstream bandwidth | | a speed test immediately before and after the run; record both |
| Latency to the backend | | `ping <backend host>` or `Test-Connection`; give the average and the worst |
| Anything else on the connection | | an office doing ordinary work is more honest than a quiet night |

## 4. The backend

| Field | Value |
|---|---|
| Host, region and instance size | |
| PostgreSQL version and instance size | |
| Number of backend replicas | |
| Concurrent users during the run (PERF-VAL-2) | |

## 5. Results

| ID | Target | Measured | Pass? |
|---|---|---|---|
| PERF-1.1 | Dashboard summary ≤ 3 s | | |
| PERF-1.2 | Full sync of the dataset ≤ 30 min | | |
| PERF-1.3 | Incremental sync, ~500 changed records ≤ 2 min | | |
| PERF-1.4 | Anomaly evidence tool call ≤ 2 s | | |

For PERF-1.1 give the **median and the worst** of at least five loads, not the best one. One
fast load proves nothing about a dashboard someone opens every morning.

For PERF-1.3, say how the ~500 changes were made (edited in Tally, or generated) and confirm the
count that actually arrived — a run that synced 50 records is not a PERF-1.3 measurement.

## 6. What went wrong

Anything that failed, retried, timed out or looked odd — a `TALLY_EXPORT_TIMEOUT`, a run that
came back PARTIAL, a restart of Tally part way through. A clean number with an unexplained retry
behind it is worse than a slower number with an explanation, because the retry is what will
happen at a customer site.

| Observation | Where it showed up |
|---|---|
| | |

## 7. Signed off

| | |
|---|---|
| Run by | |
| Date (and time zone) | |
| Recorded in `docs/progress.md` | yes / no |

---

### Before you start

- Close anything heavy on the PC. Note what you could not close.
- Let TallyPrime settle: if it has been open for days, the SRS's own "long uptime" advisory
  applies (SRS 16 row 8) and the run is measuring a tired Tally. Restart it, and say you did.
- Take `deploy/backup/take_snapshot.sh` output first if the run is against real data.
- The existing `docs/benchmarks/p8-analytics.md` and `p9-*.md` are **developer-machine** figures
  and state plainly that they are not PERF-VAL evidence. Do not merge the two.
