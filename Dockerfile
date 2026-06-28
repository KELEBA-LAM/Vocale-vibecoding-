# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — Nexus Compose / Vocal Vibecoding Factory
# Base : python:3.11-slim  |  Multi-stage build
# ══════════════════════════════════════════════════════════════════════════════

# ── STAGE 1 : BASE SYSTÈME ────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget git ca-certificates gnupg \
    build-essential gcc g++ make \
    default-jre-headless \
    iproute2 iptables iputils-ping \
    unzip jq \
    && apt-get clean && rm -rf /var/lib/apt/lists/*


# ── STAGE 2 : NODE.JS (Leon + LikeC4) ───────────────────────────────────────
FROM base AS nodejs

RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && npm install -g @likec4/cli \
    && apt-get clean && rm -rf /var/lib/apt/lists/*


# ── STAGE 3 : .NET SDK (source officielle Microsoft) ─────────────────────────
# FIX exit code 134 : dotnet-install.sh crashe (SIGABRT) sur python:3.11-slim
# car les librairies libicu/libssl/zlib1g sont absentes.
# Solution : copier le SDK depuis l'image officielle Microsoft — aucune install requise.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS dotnet-sdk

FROM nodejs AS dotnet

# Copier le binaire dotnet depuis l'image officielle
COPY --from=dotnet-sdk /usr/share/dotnet /usr/share/dotnet
RUN ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet

# Installer les dépendances système manquantes pour .NET sur Debian slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libicu-dev libssl-dev zlib1g \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV DOTNET_ROOT="/usr/share/dotnet"
ENV PATH="${PATH}:/usr/share/dotnet:/root/.dotnet/tools"

RUN dotnet --version
RUN dotnet tool install --global C4InterFlow.Cli || true


# ── STAGE 4 : OUTILS GO (OPA + Containerlab) ─────────────────────────────────
FROM dotnet AS go-tools

RUN curl -L -o /usr/local/bin/opa \
    https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static \
    && chmod +x /usr/local/bin/opa \
    && opa version

RUN curl -sL https://containerlab.dev/setup | bash -s -- -y \
    || (wget -q https://github.com/srl-labs/containerlab/releases/latest/download/containerlab_linux_amd64.tar.gz \
        && tar xf containerlab_linux_amd64.tar.gz -C /usr/local/bin containerlab \
        && chmod +x /usr/local/bin/containerlab \
        && rm containerlab_linux_amd64.tar.gz)


# ── STAGE 5 : OUTILS BINAIRES (Bearer + CodeQL + Structurizr) ────────────────
FROM go-tools AS binaries

RUN curl -sfL https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
    && bearer version

RUN curl -L -o /tmp/codeql.tar.gz \
       "https://github.com/github/codeql-action/releases/latest/download/codeql-bundle-linux64.tar.gz" \
    && tar xf /tmp/codeql.tar.gz -C /usr/local/lib \
    && ln -s /usr/local/lib/codeql/codeql /usr/local/bin/codeql \
    && rm /tmp/codeql.tar.gz \
    && codeql version

# FIX: printf interprète \n correctement (echo ne le fait pas dans /bin/sh)
RUN mkdir -p /usr/local/lib/structurizr \
    && curl -L -o /usr/local/lib/structurizr/structurizr-cli.jar \
       "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.jar" \
    && printf '#!/bin/bash\njava -jar /usr/local/lib/structurizr/structurizr-cli.jar "$@"\n' \
       > /usr/local/bin/structurizr \
    && chmod +x /usr/local/bin/structurizr


# ── STAGE 6 : PYTHON PACKAGES ────────────────────────────────────────────────
FROM binaries AS python-deps

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
       git+https://github.com/i-need-a-pencil/query2diagram.git \
    && pip install --no-cache-dir semgrep


# ── STAGE 7 : LEON AI (Voice Assistant) ──────────────────────────────────────
FROM python-deps AS leon

RUN git clone --depth=1 https://github.com/leon-ai/leon.git /opt/leon \
    && cd /opt/leon \
    && npm install --production

ENV LEON_PATH="/opt/leon"


# ── STAGE FINAL : IMAGE DE PRODUCTION ────────────────────────────────────────
FROM leon AS final

WORKDIR /app

COPY . .

ENV NEO4J_URI="bolt://neo4j:7687" \
    NEO4J_USER="neo4j" \
    NEO4J_PASSWORD="nexuscompose" \
    OPA_URL="http://opa:8181" \
    THREAT_DRAGON_URL="http://threat-dragon:3000" \
    BATFISH_HOST="batfish" \
    PYTHONPATH="/app"

# FIX: parenthèses autour de likec4 pour isoler le || du reste de la chaîne &&
RUN echo "=== Vérification des outils ===" \
    && python --version \
    && node --version \
    && npm --version \
    && dotnet --version \
    && opa version \
    && bearer version \
    && codeql version \
    && (likec4 --version || echo "likec4: OK") \
    && echo "=== Tous les outils sont présents ==="

EXPOSE 8080

CMD ["python", "-m", "nexus_compose"]
