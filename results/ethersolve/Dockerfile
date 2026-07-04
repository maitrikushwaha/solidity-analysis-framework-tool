# Reproducible EtherSolve evaluation environment
# Pins: Java 11 (paper's tested runtime), EtherSolve V1.1 (JSS-2023) jar,
#       and exact solc compiler versions via solc-select.
# Same image -> identical bytecode -> identical EtherSolve verdicts on any CPU.
FROM eclipse-temurin:11-jdk-jammy

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pre-install the exact, checksum-verified solc binaries required by the corpus
COPY scripts/install_solc.sh /tmp/install_solc.sh
RUN bash /tmp/install_solc.sh

# Pinned EtherSolve V1.1 jar (commit 59fe4412f7, sha256 77fd261027958953fbaae7406c088e9670faf4ae58a99c684ca8709aea4c6775)
COPY tool/EtherSolve.jar /opt/ethersolve/EtherSolve.jar
COPY scripts/ /opt/ethersolve/scripts/

ENV ETHERSOLVE_JAR=/opt/ethersolve/EtherSolve.jar
WORKDIR /work
ENTRYPOINT ["python3", "/opt/ethersolve/scripts/run_ethersolve.py"]
