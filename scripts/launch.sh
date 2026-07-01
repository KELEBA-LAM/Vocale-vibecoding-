#!/usr/bin/env bash
# scripts/launch.sh
# ══════════════════════════════════════════════════════════════════════════════
# Lance le système Nexus Compose complet en une seule commande.
#
# Ce script orchestre :
#   1. bootstrap.sh   — dézipe les 18 sous-systèmes, installe les packages
#   2. docker compose — construit et démarre tous les services
#
# Usage :
#   ./scripts/launch.sh                   # lancement standard (7 services)
#   ./scripts/launch.sh --fullstack       # + OpenHands (profile fullstack)
#   ./scripts/launch.sh --build-only      # construit les images sans démarrer
#   ./scripts/launch.sh --stop            # arrête proprement tous les services
#   ./scripts/launch.sh --status          # état de tous les services
#   ./scripts/launch.sh --logs [service]  # logs en temps réel
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── Options ───────────────────────────────────────────────────────────────────
MODE_FULLSTACK=false
MODE_BUILD_ONLY=false
MODE_STOP=false
MODE_STATUS=false
MODE_LOGS=false
LOGS_SERVICE=""

for arg in "$@"; do
  case "$arg" in
    --fullstack)  MODE_FULLSTACK=true  ;;
    --build-only) MODE_BUILD_ONLY=true ;;
    --stop)       MODE_STOP=true       ;;
    --status)     MODE_STATUS=true     ;;
    --logs)       MODE_LOGS=true       ;;
    -*)           true                 ;;
    *)            LOGS_SERVICE="$arg"  ;;
  esac
done

COMPOSE_FLAGS=""
$MODE_FULLSTACK && COMPOSE_FLAGS="--profile fullstack"

# ── Utilitaires ───────────────────────────────────────────────────────────────
CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'
step() { echo -e "\n${BOLD}${CYAN}▶  $*${NC}"; }
ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }

# ── Modes rapides ─────────────────────────────────────────────────────────────

if $MODE_STOP; then
  step "Arrêt de tous les services..."
  docker compose $COMPOSE_FLAGS down --remove-orphans
  ok "Services arrêtés"
  exit 0
fi

if $MODE_STATUS; then
  docker compose $COMPOSE_FLAGS ps
  exit 0
fi

if $MODE_LOGS; then
  docker compose $COMPOSE_FLAGS logs -f ${LOGS_SERVICE:-}
  exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
# LANCEMENT COMPLET
# ══════════════════════════════════════════════════════════════════════════════

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Nexus Compose — Lancement du système unifié                    ║"
$MODE_FULLSTACK && \
echo "║  Mode : FULLSTACK (inclut OpenHands)                            ║" || \
echo "║  Mode : STANDARD (7 services + 1 OpenHands optionnel)           ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Étape 1 : Bootstrap ───────────────────────────────────────────────────────
step "1/3 — Bootstrap : décompression et installation des sous-systèmes"
if ./scripts/bootstrap.sh --check 2>/dev/null; then
  echo "  Bootstrap déjà effectué — ignoré (relancer bootstrap.sh --ci pour forcer)"
else
  ./scripts/bootstrap.sh
fi

# ── Étape 2 : Build des images ────────────────────────────────────────────────
step "2/3 — Build des images Docker"
docker compose $COMPOSE_FLAGS build --parallel

if $MODE_BUILD_ONLY; then
  ok "Build terminé — démarrage ignoré (--build-only)"
  exit 0
fi

# ── Étape 3 : Démarrage ordonné ───────────────────────────────────────────────
step "3/3 — Démarrage des services (ordre de dépendance)"

# Infrastructure d'abord
echo "  Démarrage infrastructure (neo4j, opa, batfish, threat-dragon)..."
docker compose $COMPOSE_FLAGS up -d neo4j opa batfish threat-dragon

# Attendre neo4j (healthcheck)
echo "  Attente Neo4j (healthcheck)..."
TIMEOUT=90
ELAPSED=0
until docker compose exec -T neo4j cypher-shell \
        -u neo4j -p nexuscompose "RETURN 1" >/dev/null 2>&1; do
  sleep 3; ELAPSED=$((ELAPSED + 3))
  if [[ $ELAPSED -ge $TIMEOUT ]]; then
    echo -e "  ${YELLOW}⚠ Neo4j n'a pas démarré en ${TIMEOUT}s — continuons quand même${NC}"
    break
  fi
  echo -n "."
done
echo ""

# Application principale
echo "  Démarrage app (nexus-compose + leon)..."
docker compose $COMPOSE_FLAGS up -d app leon

# OpenHands (fullstack uniquement)
if $MODE_FULLSTACK; then
  echo "  Démarrage OpenHands..."
  docker compose --profile fullstack up -d openhands
fi

# ── Rapport final ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Système Nexus Compose démarré ✓                                ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
docker compose $COMPOSE_FLAGS ps
echo ""
echo "  Points d'accès :"
echo "    Neo4j Browser  → http://localhost:7474"
echo "    OPA            → http://localhost:8181"
echo "    Batfish        → http://localhost:9996"
echo "    Threat Dragon  → http://localhost:3000"
echo "    Leon AI        → http://localhost:1337"
$MODE_FULLSTACK && echo "    OpenHands      → http://localhost:3001"
echo ""
echo "  Commandes utiles :"
echo "    docker compose exec app python -m nexus_compose run      # run pipeline"
echo "    docker compose exec app python -m pytest test/ -v        # tests"
echo "    docker compose exec app python -m nexus_compose dry-run  # vérif outils"
echo "    ./scripts/launch.sh --logs app                           # logs app"
echo "    ./scripts/launch.sh --stop                               # tout arrêter"
echo ""
