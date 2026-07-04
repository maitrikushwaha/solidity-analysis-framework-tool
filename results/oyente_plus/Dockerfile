# Reproducible oyente+ image for the ACM DLT rebuttal (datasets: SBC, Qian, SolidiFI, RSD)
#
# Goal: hardware-independent, reviewer-reproducible results.
#   * python:3.11-slim base  (pin the digest below after the first build for byte-for-byte repro)
#   * z3-solver pinned to 4.14.1.0
#   * crytic-compile pinned to 0.3.8
#   * EVERY solc version the four datasets need is pre-installed, so the run script
#     only ever does `solc-select use` (offline) at run time -- never `solc-select install`.
#     That removes the network and removes timing-dependent compiler resolution.
#
# Build:   docker build -t oyente-plus-repro:latest .
#
# Base pinned by digest for byte-for-byte reproducibility (python:3.11-slim as of 2026-06-18)
FROM python:3.11-slim@sha256:ae52c5bef62a6bdd42cd1e8dffef86b9cd284bde9427da79839de7a4b983e7ca

LABEL maintainer="oyente_plus reproducible build (ACM DLT rebuttal)"

# ---- Python toolchain (pinned) ------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates git && \
    pip install --no-cache-dir --upgrade pip wheel && \
    pip install --no-cache-dir \
        cbor2 \
        crytic-compile==0.3.8 \
        requests \
        six \
        solc-select \
        typing_extensions \
        z3-solver==4.14.1.0 && \
    pip install --no-cache-dir git+https://github.com/gsalzer/ethutils.git@10f15fa5317be18d8f2252868067317cd5bb1ca4#egg=ethutils && \
    apt-get remove -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# ---- Pre-install every solc version the datasets reference --------------------
# Versions derived from a pragma scan of datasets/{sbc,qian,rsd,solidifi,examples}.
# 0.8.30 is the default current compiler; the rest cover 0.4.x / 0.5.x / 0.8.x.
# `|| echo WARN` keeps the build going if a very old binary is unavailable for
# linux-amd64; the run script logs and deterministically falls back for those.
RUN set -u; \
    for v in 0.4.0 0.4.2 0.4.9 0.4.10 0.4.11 0.4.13 0.4.15 0.4.16 0.4.18 0.4.19 \
             0.4.21 0.4.22 0.4.23 0.4.24 0.4.25 0.4.26 \
             0.5.0 0.5.1 0.5.2 0.5.6 0.5.7 0.5.8 0.5.9 0.5.10 0.5.11 0.5.17 \
             0.6.12 0.7.6 \
             0.8.0 0.8.20 0.8.28 0.8.30; do \
        solc-select install "$v" || echo "WARN: solc $v not installable on linux-amd64"; \
    done; \
    solc-select use 0.8.30; \
    echo "=== installed solc versions ===" && solc-select versions

# ---- Oyente -------------------------------------------------------------------
COPY ./oyente /oyente/
WORKDIR /oyente
RUN python3 -O -m compileall -f /oyente

# Default entrypoint is the analyzer itself. The batch run script overrides this
# with `--entrypoint bash` so it can call `solc-select use` per contract.
ENTRYPOINT ["python3", "/oyente/oyente.py"]
