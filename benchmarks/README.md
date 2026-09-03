# MPPT WebKit memory benchmark

This benchmark targets native `linux/amd64`, Debian 13, GTK 3, and WebKitGTK
API 4.1. It keeps one visible WebView loaded for the complete run. Results from
emulation, ARM64, Arch Linux, or WebKit2 API 4.0 are outside its current scope.

The topology contains Mosquitto, a WebKit-backed MPPT server, an identical
server-only control, and a controller that owns Xvfb, GTK/WebKit, the
deterministic publisher, and telemetry collection. The control health check is
TCP-only and does not issue a Dash request.

## Prerequisites

Docker with Compose is required. A host broker is not used by Compose. If it is
needed for manual checks, this repository's development host may install the
daemon at `/usr/sbin/mosquitto` even when it is absent from `PATH`.

Do not use an emulated build for memory conclusions. Confirm the host first:

```bash
test "$(uname -m)" = x86_64
docker version
docker compose version
```

## Build once and retain the image

```bash
docker compose -f benchmarks/compose.yaml build mppt-web
docker image inspect plotter-mppt-memory:debian13 \
  --format '{{index .RepoDigests 0}} {{.Id}}'
```

Record the immutable image ID when a locally built image has no repository
digest. Reuse that image without rebuilding for the unfixed and fixed runs.
The controller records a separate source-tree SHA-256 fingerprint in every run.

## Run

```bash
mkdir -p benchmark-results
docker compose -f benchmarks/compose.yaml up \
  --abort-on-container-exit --exit-code-from controller
docker compose -f benchmarks/compose.yaml cp controller:/results/. benchmark-results/
docker compose -f benchmarks/compose.yaml down
```

The controller writes as its dedicated unprivileged user into an image-owned
directory. Copy results out before `down` removes the stopped container. This
avoids depending on host bind-mount UID mappings.

For the unfixed baseline, preserve the source checkout before changing MPPT
retention/rendering code and keep the copied run directory immutable in your
results archive. The controller records runtime package versions, image/source
metadata, calibration evidence, rendered boundary lengths, and a final
classification. A run with failed calibration or rendering checks is valid
evidence only as `INCONCLUSIVE`.

The controller first tests 20x timing (50 ms publication and 25 ms Dash
refresh). It records rendered progress, completed requests, maximum concurrent
requests, catch-up time, and process failures. If 20x is not sustainable it
drains queued work, clears the server/browser state, and tests 10x (100 ms
publication). If neither rate is sustainable, it writes an `INCONCLUSIVE`
metadata record and does not run or analyze a queued workload.

The selected rate then runs one warm-up cycle, five measured cycles, and a real
60-second final idle period.
Raw CSV and JSON metadata are written beneath a UTC-named directory in
`benchmark-results/`. Analyze a completed run with:

```bash
uv run python benchmarks/analyze_memory.py \
  benchmark-results/RUN_ID/telemetry.csv
```

Each cycle boundary verifies exactly 7,200 points in all three aligned traces,
then zero points after clear. Harness or WebKit termination, render timeout,
request overlap, stalled calibration progress, or excessive catch-up makes the
run `INCONCLUSIVE`.
