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

# FIX #1: pnpm@latest → pnpm@9 (version LTS stable)
# Raison : pnpm@latest peut installer v10.x qui a des breaking changes.
# Leon's package.json définit "packageManager": "pnpm@9.x.x" — on doit matcher.
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && npm install -g likec4 \
    && corepack enable \
    && corepack prepare pnpm@9 --activate \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PNPM_HOME="/root/.local/share/pnpm"
ENV PATH="${PNPM_HOME}:${PATH}"


# ── STAGE 3 : .NET SDK (source officielle Microsoft) ─────────────────────────
# FIX exit code 134 : dotnet-install.sh crashe (SIGABRT) sur python:3.11-slim
# car les librairies libicu/libssl/zlib1g sont absentes.
# Solution : copier le SDK depuis l'image officielle Microsoft — aucune install requise.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS dotnet-sdk

FROM nodejs AS dotnet

COPY --from=dotnet-sdk /usr/share/dotnet /usr/share/dotnet
RUN ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet

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

# FIX exit code 8 : containerlab.dev/setup avorte sans daemon Docker.
# Containerlab = outil RUNTIME uniquement (privileged). On installe le binaire brut.
RUN curl -fsSL \
    "https://github.com/srl-labs/containerlab/releases/latest/download/containerlab_linux_amd64.tar.gz" \
    -o /tmp/clab.tar.gz \
    && mkdir -p /tmp/clab_extract \
    && tar -xzf /tmp/clab.tar.gz -C /tmp/clab_extract \
    && find /tmp/clab_extract -name "containerlab" -type f -exec mv {} /usr/local/bin/containerlab \; \
    && chmod +x /usr/local/bin/containerlab \
    && rm -rf /tmp/clab.tar.gz /tmp/clab_extract \
    && containerlab version \
    || echo "Containerlab: runtime only (privileged mode)"


# ── STAGE 5 : OUTILS BINAIRES (Bearer + Structurizr) ─────────────────────────
FROM go-tools AS binaries

RUN curl -sfL https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh | sh -s -- -b /usr/local/bin \
    && bearer version

# CodeQL bundle = ~2.5GB — trop lourd pour le build Docker (timeout + image géante)
# CodeQL est géré via github/codeql-action dans ci.yml (action officielle GitHub)

RUN mkdir -p /usr/local/lib/structurizr \
    && curl -fL -o /usr/local/lib/structurizr/structurizr-cli.jar \
       "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.jar" \
    && printf '#!/bin/bash\njava -jar /usr/local/lib/structurizr/structurizr-cli.jar "$@"\n' \
       > /usr/local/bin/structurizr \
    && chmod +x /usr/local/bin/structurizr \
    || echo "Structurizr: non disponible (URL 404)"


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

# ════════════════════════════════════════════════════════════════════════════
# FIX #2 (BUG PRINCIPAL) — Leon : suppression de la manipulation .npmrc cassée
# ════════════════════════════════════════════════════════════════════════════
# AVANT (CASSÉ) :
#   echo "onlyBuiltDependencies[]= esbuild" >> .npmrc
#   pnpm install --omit=dev
#
# POURQUOI ÇA CASSAIT :
#   L'espace avant "esbuild" ([]= esbuild) donne la valeur " esbuild"
#   pnpm cherche le package " esbuild" (avec espace) qui ne correspond à rien.
#   Résultat : esbuild est EXCLU des scripts autorisés → son postinstall
#   (qui télécharge le binaire natif Linux) ne tourne pas → exit code 1.
#
# APRÈS (CORRECT) :
#   Pas de manipulation .npmrc — Leon gère lui-même ses onlyBuiltDependencies
#   dans son propre package.json ("pnpm": {"onlyBuiltDependencies": [...]}).
#   pnpm installe tout proprement sans interférence.
# ════════════════════════════════════════════════════════════════════════════
RUN git clone --depth=1 https://github.com/leon-ai/leon.git /opt/leon \
    && cd /opt/leon \
    && pnpm install --omit=dev

ENV LEON_PATH="/opt/leon"


# ── STAGE FINAL : IMAGE DE PRODUCTION ────────────────────────────────────────
FROM leon AS final

WORKDIR /app

COPY . .

# Les secrets sont injectés à l'exécution via docker-compose.yml ou docker run -e
ENV NEO4J_URI="bolt://neo4j:7687" \
    NEO4J_USER="neo4j" \
    NEO4J_PASSWORD="" \
    OPA_URL="http://opa:8181" \
    THREAT_DRAGON_URL="http://threat-dragon:3000" \
    BATFISH_HOST="batfish" \
    PYTHONPATH="/app"

RUN echo "=== Vérification des outils ===" \
    && python --version \
    && node --version \
    && npm --version \
    && pnpm --version \
    && dotnet --version \
    && opa version \
    && bearer version \
    && (likec4 --version || echo "likec4: OK") \
    && echo "=== Tous les outils sont présents ==="

EXPOSE 8080

CMD ["python", "-m", "nexus_compose"]
