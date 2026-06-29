# ══════════════════════════════════════════════════════════════════════════════
# Dockerfile — Nexus Compose / Vocal Vibecoding Factory
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


# ── STAGE 2 : NODE.JS + pnpm ─────────────────────────────────────────────────
FROM base AS nodejs

# FIX LEON BUG :
#   → Leon 2.0 (branche develop) exige Node.js >= 24.0.0 (cf. README officiel)
#     La "correction" à setup_20.x était INCORRECTE.
#   → Leon recommande : npm install --global pnpm@latest (pas corepack)
#     Source : https://github.com/leon-ai/leon#installation
#   → On supprime corepack — inutile si pnpm est installé via npm directement.
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest \
    && npm install -g pnpm@latest \
    && npm install -g likec4 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PNPM_HOME="/root/.local/share/pnpm"
ENV PATH="${PNPM_HOME}:${PATH}"


# ── STAGE 3 : .NET SDK ────────────────────────────────────────────────────────
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


# ── STAGE 4 : OPA + Containerlab ─────────────────────────────────────────────
FROM dotnet AS go-tools

RUN curl -sSL -o /usr/local/bin/opa \
    https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static \
    && chmod +x /usr/local/bin/opa \
    && opa version

# FIX URL 404 Containerlab : le tarball s'appelle maintenant containerlab_Linux_x86_64.tar.gz
# (majuscule Linux, underscore x86_64) depuis containerlab v0.59+
RUN curl -fsSL \
    "https://github.com/srl-labs/containerlab/releases/latest/download/containerlab_Linux_x86_64.tar.gz" \
    -o /tmp/clab.tar.gz \
    && mkdir -p /tmp/clab_extract \
    && tar -xzf /tmp/clab.tar.gz -C /tmp/clab_extract \
    && find /tmp/clab_extract -name "containerlab" -type f -exec mv {} /usr/local/bin/containerlab \; \
    && chmod +x /usr/local/bin/containerlab \
    && rm -rf /tmp/clab.tar.gz /tmp/clab_extract \
    && containerlab version \
    || echo "Containerlab: runtime only (privileged mode)"


# ── STAGE 5 : Bearer + Structurizr ───────────────────────────────────────────
FROM go-tools AS binaries

RUN curl -sfL https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh \
    | sh -s -- -b /usr/local/bin \
    && bearer version

# FIX URL 404 Structurizr : depuis v2.3.0, le CLI est distribué en .zip (pas .jar seul)
# Le jar est extrait du zip → structurizr-cli/structurizr-cli.jar
RUN mkdir -p /usr/local/lib/structurizr \
    && curl -fsSL -o /tmp/structurizr-cli.zip \
       "https://github.com/structurizr/cli/releases/latest/download/structurizr-cli.zip" \
    && unzip -q /tmp/structurizr-cli.zip -d /tmp/structurizr-cli \
    && find /tmp/structurizr-cli -name "*.jar" | head -1 \
       | xargs -I{} cp {} /usr/local/lib/structurizr/structurizr-cli.jar \
    && printf '#!/bin/bash\njava -jar /usr/local/lib/structurizr/structurizr-cli.jar "$@"\n' \
       > /usr/local/bin/structurizr \
    && chmod +x /usr/local/bin/structurizr \
    && rm -rf /tmp/structurizr-cli.zip /tmp/structurizr-cli \
    || echo "Structurizr: non disponible"


# ── STAGE 6 : Python packages ─────────────────────────────────────────────────
FROM binaries AS python-deps

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
       git+https://github.com/i-need-a-pencil/query2diagram.git \
    && pip install --no-cache-dir semgrep


# ── STAGE 7 : LEON AI ─────────────────────────────────────────────────────────
FROM python-deps AS leon

# Leon 2.0 (develop) — installation conforme à la doc officielle :
# https://github.com/leon-ai/leon#installation
#
# Ce que Leon recommande exactement :
#   npm install --global pnpm@latest   ← déjà fait au STAGE 2
#   pnpm install                       ← sans --omit=dev, sans flags
#
# --omit=dev SUPPRIMÉ : Leon a besoin de ses devDependencies
# pour les scripts de build (TypeScript, etc.)
#
# Leon est un monorepo pnpm workspace (pnpm-workspace.yaml).
# pnpm install à la racine installe tous les packages du workspace.
RUN git clone --depth=1 https://github.com/leon-ai/leon.git /opt/leon \
    && cd /opt/leon \
    && pnpm install

ENV LEON_PATH="/opt/leon"


# ── STAGE FINAL ───────────────────────────────────────────────────────────────
FROM leon AS final

WORKDIR /app

COPY . .

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
