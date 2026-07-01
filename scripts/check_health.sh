#!/usr/bin/env bash
# scripts/check_health.sh
# ══════════════════════════════════════════════════════════════════════════════
# Vérifie l'état de tous les services du système Nexus Compose.
# Peut être lancé depuis l'hôte ou depuis l'intérieur du conteneur `app`.
#
# Usage :
#   ./scripts/check_health.sh            # vérifie tout
#   ./scripts/check_health.sh --json     # sortie JSON (pour intégration CI)
#   ./scripts/check_health.sh --watch    # rafraîchit toutes les 5 secondes
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Détection du contexte (hôte vs conteneur) ─────────────────────────────────
if grep -q "docker\|container" /proc/1/cgroup 2>/dev/null; then
  NEO4J_HOST="${NEO4J_HOST:-neo4j}"
  OPA_HOST="${OPA_HOST:-opa}"
  BATFISH_HOST="${BATFISH_HOST:-batfish}"
  THREAT_DRAGON_HOST="${THREAT_DRAGON_HOST:-threat-dragon}"
  LEON_HOST="${LEON_HOST:-leon}"
  OPENHANDS_HOST="${OPENHANDS_HOST:-openhands}"
else
  NEO4J_HOST="${NEO4J_HOST:-localhost}"
  OPA_HOST="${OPA_HOST:-localhost}"
  BATFISH_HOST="${BATFISH_HOST:-localhost}"
  THREAT_DRAGON_HOST="${THREAT_DRAGON_HOST:-localhost}"
  LEON_HOST="${LEON_HOST:-localhost}"
  OPENHANDS_HOST="${OPENHANDS_HOST:-localhost}"
fi

# Ports
NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
NEO4J_BOLT_PORT="${NEO4J_BOLT_PORT:-7687}"
OPA_PORT="${OPA_PORT:-8181}"
BATFISH_PORT="${BATFISH_PORT:-9996}"
THREAT_DRAGON_PORT="${THREAT_DRAGON_PORT:-3000}"
LEON_PORT="${LEON_PORT:-1337}"
OPENHANDS_PORT="${OPENHANDS_PORT:-3001}"

# ── Options ───────────────────────────────────────────────────────────────────
OUTPUT_JSON=false
WATCH_MODE=false

for arg in "$@"; do
  case "$arg" in
    --json)  OUTPUT_JSON=true  ;;
    --watch) WATCH_MODE=true   ;;
  esac
done

# ── Couleurs ──────────────────────────────────────────────────────────────────
if $OUTPUT_JSON; then
  GREEN=""; RED=""; YELLOW=""; CYAN=""; NC=""; BOLD=""
else
  GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
  CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'
fi

# ── Fonction de vérification HTTP ─────────────────────────────────────────────
# check_http LABEL URL [TIMEOUT_S]
check_http() {
  local label="$1"
  local url="$2"
  local timeout="${3:-3}"
  if curl -sf --connect-timeout "$timeout" --max-time "$timeout" "$url" > /dev/null 2>&1; then
    echo "ok"
  else
    echo "down"
  fi
}

# check_tcp LABEL HOST PORT [TIMEOUT_S]
check_tcp() {
  local host="$1"
  local port="$2"
  local timeout="${3:-3}"
  if (echo > /dev/tcp/"$host"/"$port") 2>/dev/null; then
    echo "ok"
  else
    echo "down"
  fi
}

# ── Boucle principale ─────────────────────────────────────────────────────────
run_checks() {
  declare -A STATUS

  # Neo4j HTTP
  STATUS[neo4j_http]=$(check_http "Neo4j HTTP" "http://${NEO4J_HOST}:${NEO4J_HTTP_PORT}")
  # Neo4j Bolt (TCP)
  STATUS[neo4j_bolt]=$(check_tcp "$NEO4J_HOST" "$NEO4J_BOLT_PORT")
  # OPA
  STATUS[opa]=$(check_http "OPA" "http://${OPA_HOST}:${OPA_PORT}/health")
  # Batfish (thrift port)
  STATUS[batfish]=$(check_tcp "$BATFISH_HOST" "$BATFISH_PORT")
  # Threat Dragon
  STATUS[threat_dragon]=$(check_http "Threat Dragon" "http://${THREAT_DRAGON_HOST}:${THREAT_DRAGON_PORT}")
  # Leon
  STATUS[leon]=$(check_http "Leon" "http://${LEON_HOST}:${LEON_PORT}/api/v1/healthz" \
                 || check_tcp "$LEON_HOST" "$LEON_PORT")
  # OpenHands (profile fullstack)
  STATUS[openhands]=$(check_http "OpenHands" "http://${OPENHANDS_HOST}:${OPENHANDS_PORT}/health")
  # nexus_compose Python environment
  STATUS[nexus_python]=$(python3 -c "import nexus_compose; print('ok')" 2>/dev/null || echo "down")

  if $OUTPUT_JSON; then
    python3 - <<PYEOF
import json, sys

status = {
    "neo4j_http":    "${STATUS[neo4j_http]}",
    "neo4j_bolt":    "${STATUS[neo4j_bolt]}",
    "opa":           "${STATUS[opa]}",
    "batfish":       "${STATUS[batfish]}",
    "threat_dragon": "${STATUS[threat_dragon]}",
    "leon":          "${STATUS[leon]}",
    "openhands":     "${STATUS[openhands]}",
    "nexus_python":  "${STATUS[nexus_python]}",
}
up = sum(1 for v in status.values() if v == "ok")
total = len(status)
output = {
    "summary": {"up": up, "total": total, "healthy": up == total},
    "services": status,
}
print(json.dumps(output, indent=2))
sys.exit(0 if up == total else 1)
PYEOF
    return
  fi

  # Affichage humain
  clear 2>/dev/null || true
  echo -e "${BOLD}${CYAN}"
  echo "╔══════════════════════════════════════════════════════════════════╗"
  echo "║  Nexus Compose — État des services                              ║"
  printf "║  %s                           ║\n" "$(date '+%Y-%m-%d %H:%M:%S')"
  echo "╚══════════════════════════════════════════════════════════════════╝"
  echo -e "${NC}"

  TOTAL=0; UP=0
  print_status() {
    local label="$1"
    local svc="$2"
    local detail="$3"
    TOTAL=$((TOTAL + 1))
    if [[ "${STATUS[$svc]}" == "ok" ]]; then
      UP=$((UP + 1))
      printf "  ${GREEN}✓${NC}  %-22s %s\n" "$label" "$detail"
    else
      printf "  ${RED}✗${NC}  %-22s %s\n" "$label" "${YELLOW}INJOIGNABLE${NC} ($detail)"
    fi
  }

  print_status "Neo4j HTTP"      "neo4j_http"    "http://${NEO4J_HOST}:${NEO4J_HTTP_PORT}"
  print_status "Neo4j Bolt"      "neo4j_bolt"    "bolt://${NEO4J_HOST}:${NEO4J_BOLT_PORT}"
  print_status "OPA"             "opa"           "http://${OPA_HOST}:${OPA_PORT}/health"
  print_status "Batfish"         "batfish"       "${BATFISH_HOST}:${BATFISH_PORT}"
  print_status "Threat Dragon"   "threat_dragon" "http://${THREAT_DRAGON_HOST}:${THREAT_DRAGON_PORT}"
  print_status "Leon AI"         "leon"          "http://${LEON_HOST}:${LEON_PORT}"
  print_status "OpenHands [FS]"  "openhands"     "http://${OPENHANDS_HOST}:${OPENHANDS_PORT}"
  print_status "nexus_compose"   "nexus_python"  "python3 -c 'import nexus_compose'"

  echo ""
  if [[ $UP -eq $TOTAL ]]; then
    echo -e "  ${GREEN}${BOLD}Tous les services sont opérationnels ($UP/$TOTAL) ✓${NC}"
  elif [[ $UP -gt 0 ]]; then
    echo -e "  ${YELLOW}${BOLD}$UP/$TOTAL services opérationnels${NC}"
    echo -e "  ${YELLOW}OpenHands nécessite --profile fullstack${NC}"
  else
    echo -e "  ${RED}${BOLD}Aucun service opérationnel ($UP/$TOTAL)${NC}"
    echo -e "  ${YELLOW}Lancez : ./scripts/launch.sh${NC}"
  fi
  echo ""
}

# ── Exécution ─────────────────────────────────────────────────────────────────
if $WATCH_MODE; then
  echo "Mode surveillance actif — Ctrl+C pour arrêter"
  while true; do
    run_checks
    sleep 5
  done
else
  run_checks
fi
