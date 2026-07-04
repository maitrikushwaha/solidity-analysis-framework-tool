# Reproducible Vandal image for smart-contract reentrancy analysis.
# Pins: Ubuntu 18.04, Souffle 2.0.2, Vandal @ commit d2b004326fee33920c313e64d0970410b1933990
# Vandal analysis is deterministic and CPU-independent: identical bytecode -> identical verdict.
# Base is 18.04 (bionic): the Souffle 2.0.2 .deb depends on libffi6, absent from 20.04.
FROM ubuntu:18.04

ENV DEBIAN_FRONTEND=noninteractive

# Toolchain: python3 (decompiler), Souffle runtime deps, git, curl.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip git curl ca-certificates \
        libsqlite3-0 libffi6 zlib1g libgomp1 mcpp \
    && rm -rf /var/lib/apt/lists/*

# Pin Souffle 2.0.2 (released 2020-08, contemporaneous with the Vandal commit).
RUN curl -fsSL -o /tmp/souffle.deb \
        https://github.com/souffle-lang/souffle/releases/download/2.0.2/souffle_2.0.2-1_amd64.deb \
    && apt-get update && apt-get install -y /tmp/souffle.deb \
    && rm -f /tmp/souffle.deb && rm -rf /var/lib/apt/lists/* \
    && souffle --version

# Vandal's decompiler only needs networkx; pin the version from requirements.txt.
RUN pip3 install --no-cache-dir networkx==1.11

# Pin Vandal at the exact commit.
RUN git clone https://github.com/usyd-blockchain/vandal.git /opt/vandal \
    && git -C /opt/vandal checkout d2b004326fee33920c313e64d0970410b1933990

WORKDIR /work
ENV PATH="/opt/vandal/bin:${PATH}"
