# MPPT memory investigation and remediation plan

## Objective

Diagnose and remediate unbounded memory growth observed while displaying the
MPPT Dash plot continuously in a GTK 3 WebKit WebView. In production, one MPPT
sample is published each second for 7,200 seconds, the plot is cleared, other
measurements run for about 20 seconds, and the sequence repeats. After roughly
two weeks, the WebKit process reports an out-of-memory error.

The first reproducible benchmark targets native `linux/amd64` using Debian 13,
GTK 3, and WebKitGTK 2.52/API 4.1. Testing on the ARM64 Raspberry Pi 5 and the
deployed Arch/WebKit2 4.0 environment is explicitly deferred.

The MPPT WebView must remain continuously loaded and visible. Do not simulate
tab switching.

## Success criteria

The work is complete when:

1. The benchmark can drive and verify the full MPPT workload in Docker.
2. The unfixed implementation has a preserved benchmark report, regardless of
   whether its result is `REPRODUCED`, `NOT_DETECTED`, or `INCONCLUSIVE`.
3. MPPT server and browser trace storage are bounded by construction.
4. Sliding-window and downsampling modes are implemented and tested.
5. Full-figure round trips are replaced with incremental browser updates.
6. Clear explicitly resets server and browser state.
7. The fixed implementation passes functional, packaging, MQTT, and memory
   validation described below.

Baseline reproduction is desirable but is not a gate for implementing the
fixes. If the baseline is not reproduced, report that limitation honestly; do
not claim the observed production leak was proved fixed.

## Stage 0: inspect and preserve the starting point

Before editing runtime behavior:

1. Run the existing pytest suite with `uv run pytest`.
2. Run `uv sync --group test --locked` and confirm the lockfile is current.
3. Build the package with `uv build`.
4. Record `git status`, the current commit, and a hash of the working-tree
   source used by the benchmark. The working tree may contain intentional user
   changes; do not discard them.
5. Confirm Mosquitto, Docker, and Compose are usable.
6. Record the host architecture and Docker versions.

## Stage 1: add only the controls required by the benchmark

Add these arguments to `mppt-plotter` before taking the baseline:

```text
--update-interval-ms 500
--dashport 8053
```

Requirements:

- Defaults must preserve current production behavior.
- The update interval must be a positive integer.
- The port must be valid.
- The selected interval must configure the existing `dcc.Interval` before the
  Dash server starts.
- The selected port must be passed to `app.run`.
- Add pytest coverage for defaults, overrides, and invalid values.

Do not add point limiting, downsampling, incremental Plotly updates, or new
clear behavior yet. The baseline must otherwise exercise the current plotting
implementation.

## Stage 2: create the reproducible benchmark environment

Add maintained tooling under:

```text
benchmarks/
├── README.md
├── compose.yaml
├── Dockerfile
├── run_mppt_memory.py
├── webkit_view.py
└── analyze_memory.py
```

Names may vary slightly if a clearer organization emerges, but preserve the
separation between orchestration, WebKit hosting, and analysis.

Add `benchmark-results/` to `.gitignore`. Raw telemetry and generated reports
belong there and must not be packaged in the wheel.

### Docker requirements

Use a Debian 13 benchmark image with:

- GTK 3
- WebKitGTK API 4.1
- Xvfb and xauth
- Python/PyGObject
- the locked plotter dependencies
- tools needed for process inspection

Use a multi-container Compose topology:

1. Mosquitto broker.
2. MPPT plotter loaded by WebKit.
3. Identical server-only MPPT control receiving the same MQTT traffic but no
   Dash requests.
4. Benchmark controller containing the minimal GTK/WebKit WebView, deterministic
   publisher, telemetry collector, and analyzer.

Do not impose a hard container memory limit for the initial benchmark. Run as
an unprivileged user where possible and do not disable WebKit sandboxing merely
for convenience. Add health checks/readiness checks so measurement starts only
after the broker, both plotters, and the rendered Dash page are ready.

For reproducible pre/post comparisons:

- Build and retain the benchmark image once.
- Record its immutable image digest.
- Reuse the same system/runtime image for the unfixed and fixed runs.
- Record the application source fingerprint separately for every run.
- Record installed versions of WebKitGTK, GTK, Python, Dash, Plotly, NumPy,
  Paho MQTT, Mosquitto, and relevant Docker components.

Only `linux/amd64` is in scope initially. Keep the Dockerfile portable enough
to add native `linux/arm64` later, but do not use emulation for memory results.

## Stage 3: implement benchmark workload and correctness checks

### Deterministic input

Publish exactly one row per MQTT message using:

- voltage varying deterministically between 0.70 and 0.75 V;
- current varying deterministically between -0.020 and -0.018 A;
- pixel area of 1.0 cm²;
- monotonically increasing simulated instrument timestamps;
- fixed device metadata; and
- a smooth multi-frequency formula with no unseeded randomness.

Publish to the existing `data/raw/mppt_measurement` topic at QoS 2. Clear using
the existing `plotter/mppt_measurement/clear` interface.

### Cycle shape

Each cycle contains exactly 7,200 data messages followed by a clear. The
production 20-second gap between MPPT runs is scaled with the selected
acceleration rate. At 20×, use a one-second gap. After the final clear, observe
memory for a real, unscaled 60 seconds.

Run one warm-up cycle followed by five measured cycles.

### Automatic acceleration calibration

Before the measured run:

1. Try 20× acceleration: publish every 50 ms and refresh Dash every 25 ms.
2. Measure callback completion and rendered trace progress.
3. If HTTP callbacks overlap persistently, the renderer stalls, or trace state
   falls behind, restart cleanly and try 10× acceleration.
4. Use the fastest sustainable rate.
5. Record the chosen rate and calibration evidence.
6. If neither rate is sustainable, classify the benchmark as `INCONCLUSIVE`;
   do not analyze queued work as a memory leak.

### Rendered-state verification

Use minimal JavaScript probes at cycle boundaries, not continuous invasive
instrumentation. Verify:

- all three MPPT traces reach exactly 7,200 points before each baseline clear;
- all three traces contain zero points after each clear; and
- the page and WebKit web process remain alive.

Wait for the rendered clear before beginning the next cycle. A flat memory
result is invalid if the complete graph workload was not rendered.

## Stage 4: collect and analyze the unfixed baseline

### Telemetry

At fixed intervals and all phase boundaries, collect RSS, PSS, and private
memory from `/proc/*/smaps_rollup` for:

- the GTK harness;
- each WebKit web, network, and GPU process;
- the WebKit-backed MPPT Python process/container;
- the server-only MPPT Python process/container; and
- Mosquitto.

Also record:

- timestamps and cycle/phase markers;
- points published;
- completed Dash requests/callbacks;
- rendered trace lengths;
- process IDs and restarts;
- container current/peak memory; and
- errors from GTK, WebKit, Dash, MQTT, and the browser console.

Write raw samples to CSV and metadata/classification to JSON under a unique
directory in `benchmark-results/`.

### Early stop

Never stop before three measured cycles. Stop early as an unmistakable
reproduction only if post-clear WebKit PSS:

- increases after every measured cycle;
- has a linear-fit R² of at least 0.98;
- grows by at least the greater of 10 MiB/cycle or 2% of post-warm-up PSS per
  cycle; and
- grows by at least 50 MiB in total.

### Final classification

Use three possible results:

- `REPRODUCED`: rendering checks pass and post-clear WebKit PSS shows material,
  consistent positive growth.
- `NOT_DETECTED`: rendering checks pass and memory reaches a bounded plateau
  under this workload.
- `INCONCLUSIVE`: rendering/backlog checks fail, processes restart, samples are
  too noisy, or the result is borderline.

After all five cycles, material growth requires:

- slope of at least the greater of 2 MiB/cycle or 0.5% of post-warm-up WebKit
  PSS per cycle;
- at least four of five post-clear measurements increasing; and
- at least 10 MiB total post-clear growth.

Treat an elevated but bounded allocator plateau as acceptable. Do not require
RSS or PSS to return to its startup value after clear.

Preserve the unfixed results before changing the data or rendering design.
Proceed with Stage 5 even if the result is `NOT_DETECTED` or `INCONCLUSIVE`.

**Status (2026-09-03): complete.** The preserved unfixed baseline is at
`benchmark-results/20260903T121441Z/`. It ran at 10x acceleration after the
20x calibration was unsustainable, rendered 7,200 points in every trace and
cleared all traces for each measured cycle, and was classified `NOT_DETECTED`.
Post-clear WebKit PSS had a slope of 857.6 KiB/cycle with R² 0.00729. This
does not reproduce or disprove the production failure on its deployed stack.

## Stage 5: implement the combined bounded-memory fix

Implement the following changes as one coherent change set. Do not split them
into individually benchmarked fixes; the project considers all of them
worthwhile. Accept that the benchmark will not attribute improvement to a
single mechanism.

### CLI and hard bounds

Add:

```text
--max-points 5000
--point-limit-strategy downsample
```

Requirements:

- `--max-points` must be a strictly positive integer.
- Strategies are `sliding` and `downsample`.
- `downsample` is the default.
- Every server-side and browser-side trace must remain at or below
  `max-points`, including transient update paths.
- Runs at or below the cap must preserve every point unchanged.
- The bound applies only to visualization state. The current project has no
  processed-data publication path to preserve.

### Replace repeated array copying

Remove per-message `np.append` growth from the MPPT hot path. Use an explicitly
bounded data structure suitable for append and clear. Avoid retaining old
arrays, figures, serialized payloads, or callback state after clear.

### Sliding strategy

Retain the newest `max-points` aligned rows and discard the oldest. Preserve
alignment between time, current density, power, voltage, and original
instrument timestamp.

### Downsampling strategy

Implement a deterministic streaming min/max envelope:

- cover the complete run time span;
- preserve first and latest points;
- divide older history into time buckets;
- retain extrema from current density, power, and voltage;
- deduplicate points that are extrema for multiple signals;
- keep retained points in chronological order;
- use the same selected timestamps for all three traces;
- never retain an unbounded raw history behind the displayed sample; and
- never exceed `max-points`, even temporarily in retained application state.

Document the unavoidable information loss after the cap is exceeded.

### Incremental Dash/Plotly updates

Stop passing the complete browser figure through
`State("g3", "figure")` and returning the full history every interval. Use an
incremental update mechanism appropriate to the installed Dash/Plotly version
for normal appends.

The design must still handle downsampling compaction, which may require a
bounded full-trace replacement when retained historical points change. Normal
single-point updates should not serialize all existing points.

### Explicit clear behavior

On clear:

- release/reset the server retention structure and aggregation state;
- explicitly replace or purge all three browser traces;
- reset time-offset state;
- ensure a clear is observable and acknowledged by the benchmark; and
- prevent a pre-clear callback response from repopulating cleared data.

Account for races between MQTT handling and Dash callbacks rather than relying
on timing alone. Consider an epoch/generation identifier if needed.

## Stage 6: automated tests for the fix and benchmark

Keep the ordinary pytest suite fast. Add coverage for:

- all new CLI defaults and validation;
- update interval and Dash port application;
- bounded append behavior;
- sliding-window ordering and eviction;
- unchanged points below the cap;
- downsampling never exceeding the cap;
- first/latest-point preservation;
- extrema preservation across all three signals;
- aligned timestamps across traces;
- repeated compaction without unbounded hidden state;
- complete clear/reset behavior;
- clear/update race handling;
- MQTT message decoding and MPPT state updates;
- incremental update payload size/shape;
- browser trace caps where practical;
- `/proc` memory parsing;
- process classification;
- slope and R² calculations;
- all three result classifications; and
- early-stop rules.

The long Docker benchmark must remain an explicit command and must not run as
part of ordinary `uv run pytest` or default CI.

**Status (2026-09-03): complete.** The automated suite covers CLI validation,
bounded retention for both strategies, downsampling extrema and alignment,
repeated compaction and clear, MQTT decoding and MPPT state updates, bounded
Dash `Patch` payloads, idle suppression, browser-trace clearing, callback
revision races, `/proc` parsing, classification, and early-stop rules. The
long fixed Docker benchmark is separately skipped as recorded in Stage 7.

## Stage 7: run the fixed benchmark

Run the identical calibrated workload using:

- the same immutable benchmark runtime image;
- the same architecture;
- the same Compose topology;
- the same deterministic payload stream;
- the same selected acceleration rate, if sustainable;
- one warm-up plus five measured cycles; and
- the same telemetry and analysis code.

For the fixed run, rendered traces should remain at or below the default cap of
5,000 points, then clear to zero. Add separate shorter functional checks that
exceed 5,000 points and verify both sliding and downsampling caps.

The fixed benchmark passes when:

1. It completes without renderer backlog, process restart, or WebKit error.
2. All rendered-state checks pass.
3. Post-clear WebKit PSS slope is at least 90% lower than the unfixed baseline
   if the unfixed slope was measurable.
4. Fixed memory is below the material-growth threshold and classified
   `NOT_DETECTED`.
5. The WebKit-backed and server-only plotter memory remains bounded.
6. No continuing upward trend is detected during the final real 60-second idle
   period.

If the unfixed baseline was not `REPRODUCED`, requirements 3 and any claim of a
demonstrated leak fix do not apply. The fixed run must still establish bounded
storage, correct rendering, and `NOT_DETECTED` under the benchmark.

**Status (2026-09-03): skipped by project decision.** The unfixed benchmark
was classified `NOT_DETECTED`, so no comparative fixed benchmark will be run.
The bounded-storage implementation remains covered by unit and manual host
tests, but this decision does not establish behavior on the production
Raspberry Pi/Arch/WebKit stack or multi-week workloads.

## Stage 8: final validation and handoff

Before completion:

1. Run `uv sync --group test --locked`.
2. Run `uv run pytest`.
3. Run `uv run python -m compileall -q src tests tools benchmarks`.
4. Run the broker-backed MQTT integration checks.
5. Build distributions with `uv build`.
6. Inspect the wheel for Python modules, CSS, console entry points, license, and
   all five systemd units. Ensure benchmark code/results are not in the wheel.
7. Run `git diff --check`.
8. Document the exact benchmark commands, image digest, run durations,
   classifications, slopes, peaks, and result artifact paths.
9. State explicitly whether the original production leak was reproduced.
10. List deferred validation: native ARM64/Raspberry Pi 5, Arch Linux, and the
    actual deployed WebKit2 4.0 stack.

Do not describe a short amd64/WebKitGTK 4.1 result as proof for all platforms or
multi-week workloads.

**Status (2026-09-03): complete, except for the deliberately skipped Stage 7
comparison.** Final checks used `uv sync --group test --locked`, `uv run
pytest` (39 passed), `python -m compileall -q src tests tools benchmarks`, and
`git diff --check`. A broker-backed host check used the existing local
Mosquitto service on port 1883: 15 MPPT messages reached a temporary Dash
server with `--max-points 10`, its returned trace coordinate arrays were each
bounded at six points, and an MQTT clear explicitly returned six empty trace
arrays. `uv build` produced the source distribution and wheel; inspection
confirmed the five console scripts, five systemd units, CSS asset, license,
and `mppt_retention.py`, with no benchmark results in the wheel.

The baseline command was `docker compose -f benchmarks/compose.yaml up
--abort-on-container-exit --exit-code-from controller`; its runtime image was
`plotter-mppt-memory@sha256:f606134b7671efcbb7469edaa87e911a76d51548ea7d40b061e8cf2ea801c408`.
The preserved run at `benchmark-results/20260903T121441Z/` lasted 4507.47
seconds according to telemetry, used 10x acceleration, and was classified
`NOT_DETECTED`. The original production failure was not reproduced. Deferred
validation remains native ARM64/Raspberry Pi 5, the deployed Arch/WebKit2 4.0
stack, and multi-week runtime behavior.
