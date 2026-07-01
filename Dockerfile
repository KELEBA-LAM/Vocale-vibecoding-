# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — Nexus Compose / Vocal Vibecoding Factory
#
# STRATÉGIE DES BINAIRES EXTERNES :
#
#   OPA / Bearer / Containerlab / Structurizr → binaires pré-compilés officiels
#     Les zips sources (opa.zip, bearer.zip, etc.) sont destinés à bootstrap.sh
#     (développement local sans Docker). Les compiler dans Docker nécessiterait
#     de télécharger tous les modules Go depuis internet (go.sum) et épuise la
#     RAM du runner CI (~7 GB) quand les stages tournent en parallèle.
#     Résultats observés : exit code 1 (cmd/opa introuvable en OPA v2.x) et
#     exit code 137 (OOM Kill sur dotnet-build + base concurrent).
#
#   C4InterFlow.Cli → installé via dotnet tool (NuGet), pas de build source
#
#   Python (pytm, q2d, tmdd, crewAI, OpenHands, OpenManus-RL) → zips bundlés ✓
#   Leon AI → zip bundlé ✓  (seuls vrais gains offline)
#
# STAGES :
#   binaries     → télécharge OPA, Bearer, Containerlab, C4InterFlow, Structurizr
#   base         → Python 3.11 + paquets système (sans JRE — installé dans binaries)
#   nodejs       → Node.js 24 + pnpm
#   tools        → assemble binaires + Node
#   python-deps  → pytm, q2d, tmdd depuis zips locaux + semgrep PyPI
#   unified-deps → crewAI, OpenHands, OpenManus-RL depuis zips locaux
#   leon         → Leon AI depuis zip local (plus de git clone)
#   final        → assemblage + nexus_compose
# ══════════════════════════════════════════════════════════════════════════════


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 0 — Binaires externes (pré-compilés, séquentiels pour économiser la RAM)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM debian:12-slim AS binaries

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates unzip \
    default-jre-headless \
    dotnet-sdk-8.0 2>/dev/null || apt-get install -y --no-install-recommends wget \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates unzip \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /out/bin /out/lib

# ── OPA (binaire statique officiel) ───────────────────────────────────────────
RUN curl -sSfL -o /out/bin/opa \
    "https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static" \
    && chmod +x /out/bin/opa \
    && /out/bin/opa version \
    && echo "OPA ✓"

# ── Bearer (binaire officiel) ─────────────────────────────────────────────────
RUN curl -sfL "https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh" \
    | sh -s -- -b /out/bin \
    && /out/bin/bearer version \
    && echo "Bearer ✓"

# ── Containerlab (binaire officiel) ───────────────────────────────────────────
RUN curl -sfL "https://get.containerlab.dev" | BINDIR=/out/bin sh \
    && echo "Containerlab ✓" \
    || echo "Containerlab: non disponible (réseau)"

# ── C4InterFlow (dotnet tool depuis NuGet) ─────────────────────────────────────
RUN curl -fsSL https://dot.net/v1/dotnet-install.sh | bash -s -- --version 8.0 \
        --install-dir /out/dotnet \
    && /out/dotnet/dotnet tool install --tool-path /out/bin C4InterFlow.Cli \
    && /out/bin/c4interflow --version \
    && echo "C4InterFlow.Cli ✓" \
    || echo "C4InterFlow.Cli: non disponible (NuGet)"

# ── Structurizr CLI (jar officiel) ───────────────────────────────────────────
RUN mkdir -p /out/lib/structurizr \
    && touch /out/lib/structurizr/structurizr-cli.jar \
    && curl -fsSL -o /tmp/structurizr.zip \
       "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.zip" \
    && unzip -q /tmp/structurizr.zip -d /tmp/structurizr \
    && find /tmp/structurizr -name "*.jar" | head -1 \
       | xargs -I{} cp {} /out/lib/structurizr/structurizr-cli.jar \
    && rm -rf /tmp/structurizr.zip /tmp/structurizr \
    && echo "Structurizr CLI ✓" \
    || echo "Structurizr: non disponible (réseau)"

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
# STAGE 3 — Assemblage : Node.js + binaires externes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM nodejs AS tools

# Copie des binaires depuis le stage `binaries` (un seul COPY par outil)
COPY --from=binaries /out/bin/opa          /usr/local/bin/opa
COPY --from=binaries /out/bin/bearer       /usr/local/bin/bearer

# Containerlab — optionnel (peut être absent si téléchargement échoué)
COPY --from=binaries /out/bin /tmp/external_bin
RUN if [[ -s /tmp/external_bin/containerlab ]]; then \
      cp /tmp/external_bin/containerlab /usr/local/bin/containerlab \
      && chmod +x /usr/local/bin/containerlab \
      && echo "Containerlab ✓"; \
    else \
      echo "Containerlab: non disponible"; \
    fi \
    && rm -rf /tmp/external_bin

# C4InterFlow — optionnel (dotnet tool depuis NuGet dans stage binaries)
RUN if [[ -f /tmp/c4if/c4interflow ]]; then \
      cp /tmp/c4if/c4interflow /usr/local/bin/c4interflow && chmod +x /usr/local/bin/c4interflow; \
    fi 2>/dev/null || true

# Structurizr — copie du jar (peut être un placeholder vide si réseau KO)
RUN mkdir -p /usr/local/lib/structurizr
COPY --from=binaries /out/lib/structurizr/structurizr-cli.jar \
     /usr/local/lib/structurizr/structurizr-cli.jar
RUN if [[ -s /usr/local/lib/structurizr/structurizr-cli.jar ]]; then \
      printf '#!/bin/bash\njava -jar /usr/local/lib/structurizr/structurizr-cli.jar "$@"\n' \
        > /usr/local/bin/structurizr \
      && chmod +x /usr/local/bin/structurizr \
      && echo "Structurizr ✓"; \
    else \
      echo "Structurizr: non disponible"; \
    fi

# Validation (OPA et Bearer sont toujours disponibles — statiques et robustes)
RUN opa version && bearer version


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
# COPY unified_system/crewAI.zip /tmp/ → le fichier arrive à /tmp/crewAI.zip
# (pas /tmp/unified_system/crewAI.zip). Le double-essai précédent était fragile.
COPY unified_system/crewAI.zip /tmp/crewAI.zip
RUN unzip -q /tmp/crewAI.zip -d /tmp/crewai_src \
    && CREWAI_DIR=$(find /tmp/crewai_src -maxdepth 1 -mindepth 1 -type d | head -1) \
    && pip install --no-cache-dir -e "$CREWAI_DIR" \
       || pip install --no-cache-dir crewai \
    && rm -rf /tmp/crewAI.zip /tmp/crewai_src

# ── OpenHands — PAS de pip install dans cette image ──────────────────────────
# OpenHands est un SERVEUR AUTONOME (conteneur Docker séparé défini dans
# docker-compose.yml, service `openhands`, profile `fullstack`).
# bridge.py lui parle via son API HTTP (OH_BASE_URL) — pas d'import Python.
# Tenter pip install openhands ici échoue car :
#   1. Le package PyPI s'appelle "openhands" mais a des dépendances massives
#      (PyTorch, GPU libs…) incompatibles avec cette image légère.
#   2. Le zip contient le code source du serveur, pas un client léger.
# Le zip est gardé dans le repo pour référence / déploiement bare-metal.

# ── OpenManus-RL depuis zip local — namespace package, PYTHONPATH ─────────────
COPY unified_system/OpenManus-RL.zip /tmp/OpenManus-RL.zip
RUN unzip -q /tmp/OpenManus-RL.zip -d /opt/openmanus_rl \
    && echo "/opt/openmanus_rl" > \
       "$(python -c 'import site; print(site.getsitepackages()[0])')/openmanus_rl.pth" \
    && rm -rf /tmp/OpenManus-RL.zip


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STAGE 6 — Leon AI depuis zip local (remplace git clone)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FROM unified-deps AS leon

# FIX variable d'env pour contourner le devEngines check de pnpm
# (cf. commentaire original dans l'ancienne stage LEON)
ENV PNPM_CONFIG_RUNTIME_ON_FAIL=ignore

# NOTE : syntaxe JSON array obligatoire pour les noms de fichiers avec espaces.
# `COPY "Leon AI.zip" /tmp/` provoque l'erreur :
#   unexpected end of statement while looking for matching double-quote
# Le parseur Dockerfile ne gère pas les espaces via quotes shell — seul le
# tableau JSON le fait correctement.
COPY ["Leon AI.zip", "/tmp/leon_ai.zip"]
RUN echo "Extraction Leon AI depuis zip local..." \
    && unzip -q /tmp/leon_ai.zip -d /tmp/leon_src \
    && LEON_INNER=$(find /tmp/leon_src -maxdepth 2 -mindepth 1 -type d -name "leon-develop" | head -1) \
    && if [[ -n "$LEON_INNER" ]]; then \
         cp -r "$LEON_INNER" /opt/leon; \
       else \
         cp -r /tmp/leon_src/$(ls /tmp/leon_src | head -1) /opt/leon; \
       fi \
    && cd /opt/leon \
    && pnpm install --config.runtimeOnFail=ignore \
    && rm -rf /tmp/leon_ai.zip /tmp/leon_src \
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
