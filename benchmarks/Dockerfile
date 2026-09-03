FROM ghcr.io/astral-sh/uv:0.8.15 AS uv

FROM debian:13-slim

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gir1.2-gtk-3.0 gir1.2-webkit2-4.1 mosquitto-clients procps \
    python3 python3-gi python3-pip xauth xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /opt/plotter
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
COPY data ./data
RUN uv export --locked --no-dev --format requirements-txt --output-file /tmp/requirements.txt \
    && uv pip install --system --break-system-packages -r /tmp/requirements.txt \
    && uv pip install --system --break-system-packages --no-deps .

COPY benchmarks ./benchmarks
RUN useradd --create-home --uid 10001 benchmark \
    && mkdir -p /results \
    && chown benchmark:benchmark /results
USER benchmark
ENV PYTHONUNBUFFERED=1
