# ══════════════════════════════════════════════════════════════════════════════
# policies/main.rego — Politique OPA de base pour Nexus Compose
# FIX #7: ce dossier doit exister dans le repo pour que docker-compose monte le volume
# ══════════════════════════════════════════════════════════════════════════════

package nexus.policy

default allow = false

# Autoriser toutes les requêtes en développement
allow {
    input.env == "development"
}

# Autoriser si l'utilisateur est authentifié
allow {
    input.user.authenticated == true
}
