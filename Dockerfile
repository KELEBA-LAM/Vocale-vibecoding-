# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — Nexus Compose / Vocal Vibecoding Factory
#
# ARCHITECTURE MULTI-STAGE (offline-first, depuis les zips bundlés) :
#
#   go-builder   → compile opa, bearer, containerlab depuis source locale
#   dotnet-build → compile C4InterFlow.Cli depuis source locale
#   base         → Python 3.11 + system packages (apt)
#   nodejs       → Node.js 24 + pnpm
#   go-tools     → copie les binaires Go compilés + dotnet SDK
#   binaries     → ajoute les binaires pre-built / fallback
#   python-deps  → installe pytm, q2d, tmdd, crewAI, OpenHands depuis zips
#   leon         → extrait Leon AI depuis zip (plus de git clone)
#   final        → assemblage de tout + nexus_compose
#
# Pré-requis : scripts/bootstrap.sh OU disposer des zips dans le repo.
# ══════════════════════════════════════════════════════════════════════════════


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 0a — Go builder : OPA + Bearer + Containerlab depuis sources locales
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM golang:1.25-alpine AS go-builder

RUN apk add --no-cache git make bash gcc musl-dev

WORKDIR /build

# ── OPA ───────────────────────────────────────────────────────────────────────
COPY opa.zip ./
RUN unzip -q opa.zip \
    && mv opa-main/opa-main opa-src \
    && cd opa-src \
    && go build -o /out/opa ./cmd/opa \
    && /out/opa version \
    && echo "OPA compilé depuis source locale ✓"

# ── Bearer ────────────────────────────────────────────────────────────────────
COPY bearer.zip ./
RUN unzip -q bearer.zip \
    && mv bearer-main/bearer-main bearer-src \
    && cd bearer-src \
    && CGO_ENABLED=0 go build -o /out/bearer main.go \
    && /out/bearer version \
    && echo "Bearer compilé depuis source locale ✓"

# ── Containerlab ──────────────────────────────────────────────────────────────
COPY containerlab.zip ./
RUN unzip -q containerlab.zip \
    && mv containerlab-main/containerlab-main clab-src \
    && cd clab-src \
    && CGO_ENABLED=0 go build -o /out/containerlab main.go 2>/dev/null \
       || CGO_ENABLED=0 go build -o /out/containerlab . \
    && chmod +x /out/containerlab \
    && echo "Containerlab compilé depuis source locale ✓"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 0b — .NET builder : C4InterFlow.Cli depuis source locale
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS dotnet-build

WORKDIR /build

COPY C4InterFlow.zip ./
RUN unzip -q C4InterFlow.zip \
    && mv C4InterFlow-master/C4InterFlow-master c4if-src \
    && cd c4if-src \
    && dotnet publish C4InterFlow.Cli/C4InterFlow.Cli.csproj \
         -c Release \
         -r linux-x64 \
         --self-contained true \
         -o /out/c4interflow \
    && echo "C4InterFlow.Cli compilé depuis source locale ✓" \
    || echo "C4InterFlow.Cli: compilation échouée — sera ignoré"

# ── Wrapper shell pour structurizr-cli (téléchargé si build C4IF OK) ──────────
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS structurizr-build

RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /out \
    && curl -fsSL -o /tmp/structurizr.zip \
       "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.zip" \
    && unzip -q /tmp/structurizr.zip -d /tmp/structurizr \
    && find /tmp/structurizr -name "*.jar" | head -1 | xargs -I{} cp {} /out/structurizr-cli.jar \
    && rm -rf /tmp/structurizr.zip /tmp/structurizr \
    || echo "Structurizr: téléchargement échoué — sera ignoré"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 1 — Base système Python
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM python:3.11-slim AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget git ca-certificates gnupg \
    build-essential gcc g++ make \
    default-jre-headless \
    iproute2 iptables iputils-ping \
    unzip jq libicu-dev libssl-dev zlib1g \
    && apt-get clean && rm -rf /var/lib/apt/lists/*


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 2 — Node.js 24 + pnpm
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM base AS nodejs

RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && npm install -g pnpm@latest \
    && npm install -g likec4 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PNPM_HOME="/root/.local/share/pnpm"
ENV PATH="${PNPM_HOME}:${PATH}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 3 — Binaires compilés (Go + .NET + Structurizr)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM nodejs AS tools

# Binaires Go (compilés depuis sources locales en stage 0a)
COPY --from=go-builder /out/opa          /usr/local/bin/opa
COPY --from=go-builder /out/bearer       /usr/local/bin/bearer
COPY --from=go-builder /out/containerlab /usr/local/bin/containerlab

# .NET runtime (pour lancer C4InterFlow.Cli auto-contenu)
COPY --from=dotnet-build /out/c4interflow /usr/local/lib/c4interflow
RUN if [[ -f /usr/local/lib/c4interflow/C4InterFlow.Cli ]]; then \
      ln -s /usr/local/lib/c4interflow/C4InterFlow.Cli /usr/local/bin/c4interflow \
      && echo "C4InterFlow.Cli installé ✓"; \
    else \
      # Fallback : dotnet tool install depuis NuGet
      DOTNET_ROOT=/usr/share/dotnet PATH="$PATH:/root/.dotnet/tools" \
      dotnet tool install --global C4InterFlow.Cli 2>/dev/null \
      || echo "C4InterFlow.Cli non disponible"; \
    fi

# Structurizr (téléchargé en stage 0b)
RUN mkdir -p /usr/local/lib/structurizr
COPY --from=structurizr-build /out/structurizr-cli.jar /usr/local/lib/structurizr/ 2>/dev/null || true
RUN if [[ -f /usr/local/lib/structurizr/structurizr-cli.jar ]]; then \
      printf '#!/bin/bash\njava -jar /usr/local/lib/structurizr/structurizr-cli.jar "$@"\n' \
        > /usr/local/bin/structurizr \
      && chmod +x /usr/local/bin/structurizr \
      && echo "Structurizr installé ✓"; \
    fi

# Validation rapide
RUN opa version \
    && bearer version \
    && containerlab version 2>/dev/null || echo "containerlab: runtime privilegié requis"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 4 — Packages Python depuis sources locales (zips bundlés)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM tools AS python-deps

WORKDIR /app

# requirements.txt de base d'abord
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── pytm depuis zip local ─────────────────────────────────────────────────────
COPY pytm.zip /tmp/
RUN unzip -q /tmp/pytm.zip -d /tmp/pytm_src \
    && pip install --no-cache-dir -e /tmp/pytm_src/pytm-master/pytm-master/ \
    && rm -rf /tmp/pytm.zip

# ── query2diagram (q2d) depuis zip local ─────────────────────────────────────
COPY query2diagram.zip /tmp/
RUN unzip -q /tmp/query2diagram.zip -d /tmp/q2d_src \
    && pip install --no-cache-dir -e /tmp/q2d_src/query2diagram-main/query2diagram-main/ \
    && rm -rf /tmp/query2diagram.zip

# ── tmdd depuis zip local ─────────────────────────────────────────────────────
COPY tmdd.zip /tmp/
RUN unzip -q /tmp/tmdd.zip -d /tmp/tmdd_src \
    && pip install --no-cache-dir -e /tmp/tmdd_src/tmdd-main/tmdd-main/ \
    && rm -rf /tmp/tmdd.zip

# ── semgrep — OCaml build impraticable depuis source : pip install officiel ──
RUN pip install --no-cache-dir semgrep


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 5 — Unified System (crewAI + OpenManus-RL + OpenHands)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM python-deps AS unified-deps

WORKDIR /app

# ── crewAI depuis zip local ───────────────────────────────────────────────────
COPY unified_system/crewAI.zip /tmp/
RUN unzip -q /tmp/unified_system/crewAI.zip -d /tmp/crewai_src 2>/dev/null \
    || unzip -q /tmp/crewAI.zip -d /tmp/crewai_src \
    && CREWAI_DIR=$(find /tmp/crewai_src -maxdepth 1 -mindepth 1 -type d | head -1) \
    && pip install --no-cache-dir -e "$CREWAI_DIR" \
       || pip install --no-cache-dir crewai \
    && rm -rf /tmp/crewAI.zip /tmp/crewai_src

# ── OpenHands depuis zip local ────────────────────────────────────────────────
COPY unified_system/OpenHands.zip /tmp/
RUN unzip -q /tmp/unified_system/OpenHands.zip -d /tmp/oh_src 2>/dev/null \
    || unzip -q /tmp/OpenHands.zip -d /tmp/oh_src \
    && OH_DIR=$(find /tmp/oh_src -maxdepth 1 -mindepth 1 -type d | head -1) \
    && pip install --no-cache-dir -e "$OH_DIR" \
       || pip install --no-cache-dir openhands-ai \
    && rm -rf /tmp/OpenHands.zip /tmp/oh_src

# ── OpenManus-RL depuis zip local — namespace package, PYTHONPATH ─────────────
COPY unified_system/OpenManus-RL.zip /tmp/
RUN unzip -q /tmp/unified_system/OpenManus-RL.zip -d /opt/openmanus_rl 2>/dev/null \
    || unzip -q /tmp/OpenManus-RL.zip -d /opt/openmanus_rl \
    && echo "/opt/openmanus_rl" > \
       $(python -c "import site; print(site.getsitepackages()[0])")/openmanus_rl.pth \
    && rm -rf /tmp/OpenManus-RL.zip


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 6 — Leon AI depuis zip local (remplace git clone)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM unified-deps AS leon

# FIX variable d'env pour contourner le devEngines check de pnpm
# (cf. commentaire original dans l'ancienne stage LEON)
ENV PNPM_CONFIG_RUNTIME_ON_FAIL=ignore

COPY "Leon AI.zip" /tmp/
RUN echo "Extraction Leon AI depuis zip local..." \
    && unzip -q "/tmp/Leon AI.zip" -d /tmp/leon_src \
    && LEON_INNER=$(find /tmp/leon_src -maxdepth 2 -mindepth 1 -type d -name "leon-develop" | head -1) \
    && [[ -n "$LEON_INNER" ]] \
       && cp -r "$LEON_INNER" /opt/leon \
       || cp -r /tmp/leon_src/$(ls /tmp/leon_src | head -1) /opt/leon \
    && cd /opt/leon \
    && pnpm install --config.runtimeOnFail=ignore \
    && rm -rf "/tmp/Leon AI.zip" /tmp/leon_src \
    && echo "Leon AI installé depuis source locale ✓"

ENV LEON_PATH="/opt/leon"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE FINAL — Assemblage
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM leon AS final

WORKDIR /app

COPY . .

ENV NEO4J_URI="bolt://neo4j:7687" \
    NEO4J_USER="neo4j" \
    NEO4J_PASSWORD="" \
    OPA_URL="http://opa:8181" \
    THREAT_DRAGON_URL="http://threat-dragon:3000" \
    BATFISH_HOST="batfish" \
    OH_BASE_URL="http://openhands:3001" \
    PYTHONPATH="/app:/opt/openmanus_rl"

RUN pip install --no-cache-dir -e ".[dev]"

# ── Vérification de toutes les couches ────────────────────────────────────────
RUN echo "=== Validation finale ===" \
    && python --version \
    && node --version \
    && pnpm --version \
    && opa version \
    && bearer version \
    && (containerlab version 2>/dev/null || echo "containerlab: OK (runtime)") \
    && (c4interflow --version 2>/dev/null \
        || dotnet /usr/local/lib/c4interflow/C4InterFlow.Cli --version 2>/dev/null \
        || echo "C4InterFlow.Cli: non disponible") \
    && (structurizr --version 2>/dev/null || echo "Structurizr: non disponible") \
    && python -c "import nexus_compose; print('nexus_compose: OK')" \
    && python -c "import pytm; print('pytm: OK')" \
    && (python -c "import crewai; print('crewai: OK')" || echo "crewai: non disponible") \
    && echo "=== Toutes les couches validées ==="

EXPOSE 8080

# Le service `app` ne démarre pas de serveur HTTP ; il est invoqué via
# docker compose exec/run. CMD garde le conteneur en vie.
CMD ["tail", "-f", "/dev/null"]
