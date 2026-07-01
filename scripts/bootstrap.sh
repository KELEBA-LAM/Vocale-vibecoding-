#!/usr/bin/env bash
# scripts/bootstrap.sh
# ══════════════════════════════════════════════════════════════════════════════
# Bootstrap Nexus Compose — SANS téléchargements internet
#
# Ce script :
#   1. Dézipe les 15 sous-systèmes vers subsystems/
#   2. Dézipe crewAI / OpenManus-RL / OpenHands vers unified_system/
#   3. Installe les packages Python depuis les sources locales (pytm, q2d,
#      tmdd, crewAI, OpenHands) + ajoute openmanus_rl au PYTHONPATH
#   4. Installe nexus_compose en mode développement
#   5. Valide que tout est importable
#
# Usage :
#   ./scripts/bootstrap.sh           # installation complète
#   ./scripts/bootstrap.sh --ci      # mode CI (pip --break-system-packages)
#   ./scripts/bootstrap.sh --check   # vérifie sans réinstaller
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail
IFS=$'\n\t'

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUBSYSTEMS="${REPO_ROOT}/subsystems"
UNIFIED="${REPO_ROOT}/unified_system"

MODE_CI=false
MODE_CHECK=false
for arg in "$@"; do
  case "$arg" in
    --ci)    MODE_CI=true   ;;
    --check) MODE_CHECK=true;;
  esac
done

PIP_FLAGS="--quiet"
if $MODE_CI; then PIP_FLAGS="${PIP_FLAGS} --break-system-packages"; fi

# ── Utilitaires d'affichage ────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
fail() { echo -e "  ${RED}✗${NC}  $*"; }
step() { echo -e "\n${BOLD}${CYAN}▶  $*${NC}"; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║  Nexus Compose — Bootstrap                                      ║"
echo "║  Décompression + installation locale des 18 sous-systèmes       ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

cd "$REPO_ROOT"

# ══════════════════════════════════════════════════════════════════════════════
# MODE --check : valide sans rien installer
# ══════════════════════════════════════════════════════════════════════════════
if $MODE_CHECK; then
  step "Vérification de l'état du bootstrap..."
  MISSING=()
  for dir in leon query2diagram pytm tmdd opa bearer containerlab \
              semgrep codeql batfish neo4j threat-dragon dsl c4interflow likec4; do
    [[ -d "$SUBSYSTEMS/$dir" ]] && ok "subsystems/$dir" || { MISSING+=("$dir"); warn "subsystems/$dir manquant"; }
  done
  for dir in crewAI openmanus_rl OpenHands; do
    [[ -d "$UNIFIED/$dir" ]] && ok "unified_system/$dir" || { MISSING+=("$dir"); warn "unified_system/$dir manquant"; }
  done
  python3 -c "import nexus_compose" 2>/dev/null && ok "nexus_compose importable" || { MISSING+=("nexus_compose"); warn "nexus_compose non installé"; }
  python3 -c "import pytm"         2>/dev/null && ok "pytm importable"          || warn "pytm non installé"
  python3 -c "import q2d"          2>/dev/null && ok "q2d importable"           || warn "q2d non installé"
  python3 -c "import tmdd"         2>/dev/null && ok "tmdd importable"          || warn "tmdd non installé"
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo -e "\n${YELLOW}Bootstrap incomplet — relancer sans --check pour corriger.${NC}"
    exit 1
  fi
  echo -e "\n${GREEN}Bootstrap complet ✓${NC}"
  exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 — Extraction des 15 sous-systèmes
# ══════════════════════════════════════════════════════════════════════════════
step "1/5 — Extraction des sous-systèmes vers subsystems/"
mkdir -p "$SUBSYSTEMS"

#
# unzip_nested ZIP OUTER_DIR DEST_NAME
#   Gère le double-nesting de GitHub : repo.zip → outer/outer/...files
#   Si OUTER_DIR == "" : extraction directe (pas de nesting)
#
unzip_nested() {
  local zip="$1"    # chemin du zip
  local outer="$2"  # nom du répertoire externe (ex: "leon-develop")
  local dest="$3"   # nom final dans subsystems/

  if [[ -d "$SUBSYSTEMS/$dest" ]]; then
    ok "$dest (déjà extrait)"
    return 0
  fi

  if [[ ! -f "$zip" ]]; then
    warn "$dest ignoré — zip introuvable : $zip"
    return 0
  fi

  local tmp; tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN

  unzip -q "$zip" -d "$tmp" 2>/dev/null || { fail "unzip échoué : $zip"; return 1; }

  # Le zip GitHub a la structure outer/outer/...
  if [[ -n "$outer" ]] && [[ -d "$tmp/$outer/$outer" ]]; then
    mv "$tmp/$outer/$outer" "$SUBSYSTEMS/$dest"
  elif [[ -n "$outer" ]] && [[ -d "$tmp/$outer" ]]; then
    mv "$tmp/$outer" "$SUBSYSTEMS/$dest"
  else
    # Extraction directe — prendre le premier répertoire présent
    local first; first=$(find "$tmp" -maxdepth 1 -mindepth 1 -type d | head -1)
    if [[ -n "$first" ]]; then
      mv "$first" "$SUBSYSTEMS/$dest"
    else
      fail "Impossible de trouver le répertoire racine dans $zip"
      return 1
    fi
  fi
  ok "$dest"
}

#         ZIP                    OUTER_DIR           DEST
unzip_nested "Leon AI.zip"       "leon-develop"      "leon"
unzip_nested "query2diagram.zip" "query2diagram-main" "query2diagram"
unzip_nested "pytm.zip"          "pytm-master"        "pytm"
unzip_nested "tmdd.zip"          "tmdd-main"          "tmdd"
unzip_nested "opa.zip"           "opa-main"           "opa"
unzip_nested "bearer.zip"        "bearer-main"        "bearer"
unzip_nested "containerlab.zip"  "containerlab-main"  "containerlab"
unzip_nested "likec4.zip"        "likec4-main"        "likec4"
unzip_nested "semgrep.zip"       "semgrep-develop"    "semgrep"
unzip_nested "codeql.zip"        "codeql-main"        "codeql"
unzip_nested "Batfish.zip"       "batfish-master"     "batfish"
unzip_nested "neo4j.zip"         "neo4j"              "neo4j"
unzip_nested "threat-dragon.zip" "threat-dragon-main" "threat-dragon"
unzip_nested "dsl.zip"           "dsl-master"         "dsl"
unzip_nested "C4InterFlow.zip"   "C4InterFlow-master" "c4interflow"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 — Extraction unified_system (pas de double-nesting)
# ══════════════════════════════════════════════════════════════════════════════
step "2/5 — Extraction unified_system/ (crewAI, OpenManus-RL, OpenHands)"

unzip_direct() {
  local zip="$1"
  local dest="$2"

  if [[ -d "$dest" ]]; then
    ok "$(basename "$dest") (déjà extrait)"
    return 0
  fi

  if [[ ! -f "$zip" ]]; then
    warn "$(basename "$dest") ignoré — zip introuvable : $zip"
    return 0
  fi

  local tmp; tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN

  unzip -q "$zip" -d "$tmp" 2>/dev/null || { fail "unzip échoué : $zip"; return 1; }

  # Prendre le premier (et unique) dossier extrait
  local root; root=$(find "$tmp" -maxdepth 1 -mindepth 1 | head -1)
  if [[ -d "$root" ]]; then
    mv "$root" "$dest"
  else
    # Le zip déverse ses fichiers directement sans dossier racine
    mkdir -p "$dest"
    mv "$tmp"/* "$dest/" 2>/dev/null || true
  fi
  ok "$(basename "$dest")"
}

unzip_direct "$UNIFIED/crewAI.zip"       "$UNIFIED/crewAI"
unzip_direct "$UNIFIED/OpenManus-RL.zip" "$UNIFIED/openmanus_rl"
unzip_direct "$UNIFIED/OpenHands.zip"    "$UNIFIED/OpenHands"

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 — Installation des packages Python depuis les sources locales
# ══════════════════════════════════════════════════════════════════════════════
step "3/5 — Installation pip depuis sources locales"

pip_install_local() {
  local label="$1"
  local path="$2"
  local fallback="${3:-}"

  if [[ ! -d "$path" ]]; then
    if [[ -n "$fallback" ]]; then
      warn "$label introuvable ($path) — fallback PyPI : pip install $fallback"
      pip install $PIP_FLAGS "$fallback" || fail "Échec de l'installation de $label"
    else
      warn "$label ignoré (répertoire absent)"
    fi
    return 0
  fi

  echo -n "  Installation $label depuis $path ... "
  if pip install $PIP_FLAGS -e "$path" 2>/tmp/pip_err; then
    ok ""
  else
    if [[ -n "$fallback" ]]; then
      echo ""
      warn "Échec local, fallback PyPI : pip install $fallback"
      pip install $PIP_FLAGS "$fallback" \
        || { fail "Impossible d'installer $label (local + PyPI)"; cat /tmp/pip_err >&2; }
    else
      fail ""
      cat /tmp/pip_err >&2
    fi
  fi
}

# Packages Python purs — setup.py ou pyproject.toml à la racine
pip_install_local "pytm"     "$SUBSYSTEMS/pytm"         "pytm"
pip_install_local "q2d"      "$SUBSYSTEMS/query2diagram" "query2diagram"
pip_install_local "tmdd"     "$SUBSYSTEMS/tmdd"          "tmdd"

# crewAI — workspace pyproject.toml ; pip installe le package principal
pip_install_local "crewai"   "$UNIFIED/crewAI"           "crewai"

# OpenHands — pyproject.toml à la racine
pip_install_local "openhands" "$UNIFIED/OpenHands"       "openhands"

# OpenManus-RL — namespace package sans pyproject.toml
# → ajout au sys.path via fichier .pth dans site-packages
OPENMANUS_SRC="$UNIFIED/openmanus_rl"
if [[ -d "$OPENMANUS_SRC" ]]; then
  SITE_PKG=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null \
             || python3 -c "import sys; print(next(p for p in sys.path if 'site-packages' in p))")
  echo "$UNIFIED" > "$SITE_PKG/openmanus_rl.pth"
  ok "openmanus_rl (PYTHONPATH via .pth)"
else
  warn "openmanus_rl non extrait — bridge.py ne pourra pas importer OpenManus-RL"
fi

# Package principal nexus_compose
echo -n "  Installation nexus_compose[dev] ... "
pip install $PIP_FLAGS -e "${REPO_ROOT}[dev]" && ok "" || fail ""

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 4 — Génération de l'environnement .env si absent
# ══════════════════════════════════════════════════════════════════════════════
step "4/5 — Génération du fichier .env"

ENV_FILE="${REPO_ROOT}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'ENVEOF'
# Nexus Compose — Variables d'environnement
# Généré automatiquement par scripts/bootstrap.sh
# Renseigne les valeurs manquantes (*)

# ── Infrastructure ──────────────────────────────────────────────────────────
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=nexuscompose

OPA_URL=http://localhost:8181
THREAT_DRAGON_URL=http://localhost:3000
BATFISH_HOST=localhost

# ── Unified System (crewAI + OpenHands + OpenManus-RL) ──────────────────────
OH_BASE_URL=http://localhost:3000      # URL du serveur OpenHands
OH_TOKEN=                              # Bearer token (vide si auth off)
OPENAI_API_KEY=                        # * Clé OpenAI (requis pour crewAI)
CREWAI_LLM_MODEL=gpt-4o-mini          # Modèle LLM du crew
RL_MAX_STEPS=1000
RL_BATCH_SIZE=4

# ── Leon AI ─────────────────────────────────────────────────────────────────
LEON_LANG=fr-FR

# ── GitHub (optionnel, pour Threat Dragon) ──────────────────────────────────
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
ENVEOF
  ok ".env créé"
else
  ok ".env existant conservé"
fi

# ══════════════════════════════════════════════════════════════════════════════
# ÉTAPE 5 — Validation finale
# ══════════════════════════════════════════════════════════════════════════════
step "5/5 — Validation"

validate_import() {
  local pkg="$1"
  if python3 -c "import $pkg" 2>/dev/null; then
    ok "$pkg importable"
  else
    warn "$pkg non importable — certaines fonctionnalités seront désactivées"
  fi
}

validate_import nexus_compose
validate_import pytm
validate_import q2d
validate_import tmdd
validate_import crewai
validate_import openhands
# openmanus_rl peut nécessiter des dépendances supplémentaires
python3 -c "import sys; sys.path.insert(0,'$UNIFIED'); import openmanus_rl" 2>/dev/null \
  && ok "openmanus_rl importable" \
  || warn "openmanus_rl non importable (les dépendances RL peuvent manquer)"

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗"
echo -e "║  Bootstrap terminé ✓                                ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Pour lancer le système complet :"
echo "    docker compose up --build -d                 # tous les services"
echo "    docker compose --profile fullstack up -d     # + OpenHands"
echo "  Ou directement :"
echo "    ./scripts/launch.sh"
echo ""
