"""
nexus_compose_patch.stub_eliminator
────────────────────────────────────
Point d'entrée unique pour éliminer tous les stubs de nexus_compose.

Stratégie d'application
────────────────────────
Ce module intercepte ALL_HANDLERS après import de nexus_compose.drivers
et remplace chaque handler stub par une fonction qui lève l'exception
appropriée (NodeUnavailableError, NodeExternalProcessError, etc.).

Les 4 catégories de remplacement
──────────────────────────────────
1. DÉGRADATION SILENCIEUSE  (except → _stub_result)
   → Remplacé par un wrapper qui appelle raise_if_unavailable() AVANT
     l'exécution réelle, puis laisse passer l'exécution normale.

2. STUBS PURS LAMBDA  (_X_stub("name"))
   → Remplacé par une fonction qui lève directement l'exception appropriée.

3. PROCESSUS EXTERNES  (_lc4_serve, _opa_server)
   → Remplacé par NodeExternalProcessError avec la commande exacte.

4. FRONTEND UNIQUEMENT  (stride_js, tmbom_js, etc.)
   → Remplacé par NodeFrontendOnlyError.

Usage
─────
    # En début de session (dans nexus_bridge.py ou orchestrator.py)
    from nexus_compose_patch.stub_eliminator import apply_patch, wrap_handler_safe

    apply_patch()   # remplace tous les handlers dans ALL_HANDLERS

    # Pour un nœud spécifique :
    result = wrap_handler_safe("semgrep.semgrep_scan", ctx)
    # → retourne soit le résultat, soit un dict d'erreur structuré (jamais de stub silencieux)
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .exceptions import (
    NexusNodeError,
    NodeUnavailableError,
    NodeExecutionError,
    NodeExternalProcessError,
    NodeFrontendOnlyError,
    NodeSaasCredentialsError,
)
from .node_availability import (
    NodeAvailabilityChecker,
    TOOL_REGISTRY,
    _NODE_TO_TOOL,
)

logger = logging.getLogger(__name__)

# ── Nœuds qui sont des processus externes (jamais inline) ────────────────────

_EXTERNAL_NODES: Dict[str, str] = {
    "likec4.likec4_serve":   "likec4 start <workspace> --port 61000",
    "opa.opa_run_server":    "opa run --server -b <bundle> --addr 0.0.0.0:8181",
}

# ── Nœuds frontend-only (Vue.js / X6.js) ─────────────────────────────────────

_FRONTEND_NODES: Dict[str, str] = {
    "td.stride_js":               "td.vue/src/service/threats/models/stride.js",
    "td.linddun_js":              "td.vue/src/service/threats/models/linddun.js",
    "td.cia_js":                  "td.vue/src/service/threats/models/cia.js",
    "td.plot4ai_js":              "td.vue/src/service/threats/models/plot4ai.js",
    "td.cornucopia_js":           "td.vue/src/service/threats/models/eop/cornucopia.js",
    "td.context_generator_js_oats": "td.vue/src/service/threats/oats/context-generator.js",
    "td.tmbom_js_migration":      "td.vue/src/service/migration/tmBom/tmBom.js",
}

# ── Nœuds SaaS avec credentials requis ───────────────────────────────────────

_SAAS_NODES: Dict[str, tuple] = {
    "semgrep.semgrep_login":   ("Semgrep Cloud", ["SEMGREP_APP_TOKEN"]),
    "semgrep.semgrep_publish": ("Semgrep Cloud", ["SEMGREP_APP_TOKEN"]),
    "likec4.likec4_sync_leanix": ("LeanIX SaaS", ["LEANIX_API_TOKEN", "LEANIX_WORKSPACE"]),
}

# ── Nœuds manuels (pas de CLI automatisable) ──────────────────────────────────

_MANUAL_NODES: Dict[str, str] = {
    "q2d.migration":         "Migration de format — opération manuelle requise",
    "q2d.find_similar_items":"Déduplication Jaccard — aucun binaire disponible, "
                              "implémenter manuellement via q2d.datasets",
}


# ── Générateurs de handlers de remplacement ──────────────────────────────────

def _make_external_handler(node_id: str, command: str) -> Callable:
    """Crée un handler qui lève NodeExternalProcessError."""
    def _handler(ctx: dict) -> dict:
        raise NodeExternalProcessError(
            node_id=node_id,
            command=command,
            reason=(
                f"Ce nœud lance un serveur long-running qui ne peut pas s'exécuter "
                f"inline dans un pipeline. Lancez-le manuellement : {command}"
            ),
        )
    _handler.__name__ = f"_blocked_external_{node_id.replace('.', '_')}"
    return _handler


def _make_frontend_handler(node_id: str, source: str) -> Callable:
    """Crée un handler qui lève NodeFrontendOnlyError."""
    def _handler(ctx: dict) -> dict:
        raise NodeFrontendOnlyError(
            node_id=node_id,
            frontend_source=source,
            reason=(
                "Ce nœud est un module JavaScript qui s'exécute dans le navigateur "
                "via Vue.js/X6.js. Il n'existe pas d'API REST server-side équivalente."
            ),
        )
    _handler.__name__ = f"_blocked_frontend_{node_id.replace('.', '_')}"
    return _handler


def _make_saas_handler(node_id: str, service: str, env_vars: list) -> Callable:
    """Crée un handler qui lève NodeSaasCredentialsError."""
    def _handler(ctx: dict) -> dict:
        raise NodeSaasCredentialsError(
            node_id=node_id,
            service=service,
            env_vars=env_vars,
        )
    _handler.__name__ = f"_blocked_saas_{node_id.replace('.', '_')}"
    return _handler


def _make_manual_handler(node_id: str, reason: str) -> Callable:
    """Crée un handler qui lève NodeUnavailableError pour opération manuelle."""
    def _handler(ctx: dict) -> dict:
        raise NodeUnavailableError(
            node_id=node_id,
            reason=reason,
            install="",
            category="manual_operation",
        )
    _handler.__name__ = f"_blocked_manual_{node_id.replace('.', '_')}"
    return _handler


def _make_guarded_handler(
    original: Callable,
    node_id: str,
    checker: NodeAvailabilityChecker,
) -> Callable:
    """
    Enveloppe un handler existant avec une vérification de disponibilité
    AVANT l'exécution. Si l'outil est absent → NodeUnavailableError.
    Si l'outil est présent mais que l'exécution échoue → NodeExecutionError.
    """
    def _guarded(ctx: dict) -> dict:
        # Vérification proactive avant exécution
        checker.raise_if_unavailable(node_id)
        # Exécution normale
        try:
            result = original(ctx)
        except NexusNodeError:
            raise  # Laisser passer les erreurs Nexus typées
        except Exception as exc:
            raise NodeExecutionError(
                node_id=node_id,
                error=str(exc),
                exit_code=-1,
            ) from exc
        # Détecter les stubs résiduels qui auraient passé la garde
        if isinstance(result, dict) and result.get("_stub"):
            raise NodeUnavailableError(
                node_id=node_id,
                reason=f"Handler a retourné un stub résiduel malgré la garde : {result}",
                category="residual_stub",
            )
        return result

    _guarded.__name__ = f"_guarded_{original.__name__}"
    _guarded.__doc__  = f"[GUARDED] {original.__doc__ or ''}"
    return _guarded


# ── Application du patch ──────────────────────────────────────────────────────

_PATCH_APPLIED = False


def apply_patch() -> int:
    """
    Applique le patch sur ALL_HANDLERS de nexus_compose.drivers.

    Retourne le nombre de handlers remplacés.
    """
    global _PATCH_APPLIED
    if _PATCH_APPLIED:
        return 0

    try:
        from nexus_compose import drivers
    except ImportError:
        logger.warning("nexus_compose non importable — patch non appliqué")
        return 0

    checker    = NodeAvailabilityChecker()
    replaced   = 0
    all_h      = drivers.ALL_HANDLERS

    for node_id, handler in list(all_h.items()):

        # ── Catégorie 1 : Processus externes ──────────────────────────────
        if node_id in _EXTERNAL_NODES:
            all_h[node_id] = _make_external_handler(node_id, _EXTERNAL_NODES[node_id])
            logger.debug("PATCH external → %s", node_id)
            replaced += 1
            continue

        # ── Catégorie 2 : Frontend uniquement ─────────────────────────────
        if node_id in _FRONTEND_NODES:
            all_h[node_id] = _make_frontend_handler(node_id, _FRONTEND_NODES[node_id])
            logger.debug("PATCH frontend → %s", node_id)
            replaced += 1
            continue

        # ── Catégorie 3 : SaaS credentials requis ─────────────────────────
        if node_id in _SAAS_NODES:
            service, env_vars = _SAAS_NODES[node_id]
            all_h[node_id] = _make_saas_handler(node_id, service, env_vars)
            logger.debug("PATCH saas → %s", node_id)
            replaced += 1
            continue

        # ── Catégorie 4 : Opérations manuelles ────────────────────────────
        if node_id in _MANUAL_NODES:
            all_h[node_id] = _make_manual_handler(node_id, _MANUAL_NODES[node_id])
            logger.debug("PATCH manual → %s", node_id)
            replaced += 1
            continue

        # ── Catégorie 5 : Handlers avec dégradation silencieuse ───────────
        # (tous les nœuds connus qui ont un outil associé)
        if node_id in _NODE_TO_TOOL:
            all_h[node_id] = _make_guarded_handler(handler, node_id, checker)
            logger.debug("PATCH guarded → %s", node_id)
            replaced += 1
            continue

    _PATCH_APPLIED = True
    logger.info("stub_eliminator: %d handlers patchés dans ALL_HANDLERS", replaced)
    return replaced


def wrap_handler_safe(
    node_id: str,
    ctx: dict,
    handlers: Optional[Dict[str, Callable]] = None,
) -> dict:
    """
    Exécute un handler de manière sécurisée.
    Traduit toutes les exceptions NexusNodeError en dicts structurés
    (jamais de stub silencieux, jamais d'exception non catchée).

    Usage dans nexus_bridge.py :
        result = wrap_handler_safe("semgrep.semgrep_scan", ctx)
        if result.get("_unavailable"):
            leon.answer({"key": "node_unavailable", "data": result})
        else:
            leon.answer({"key": "node_success", ...})
    """
    if handlers is None:
        try:
            from nexus_compose.drivers import ALL_HANDLERS
            handlers = ALL_HANDLERS
        except ImportError:
            return {
                "_unavailable": True,
                "node_id": node_id,
                "reason": "nexus_compose non installé",
                "install": "pip install -e 'Nexus Vibecoding/'",
                "category": "missing_package",
            }

    handler = handlers.get(node_id)
    if not handler:
        return {
            "_unavailable": True,
            "node_id": node_id,
            "reason": f"Nœud inconnu '{node_id}'",
            "install": "",
            "category": "unknown_node",
        }

    try:
        result = handler(ctx)
        # Détecter les stubs résiduels non patchés
        if isinstance(result, dict) and result.get("_stub"):
            return {
                "_unavailable": True,
                "node_id":  result.get("_fn", node_id),
                "reason":   f"Stub résiduel — outil absent : {result}",
                "install":  NodeUnavailableError.INSTALL_HINTS.get(
                    node_id.split(".")[0], {}
                ).get("install", ""),
                "category": "residual_stub",
            }
        return result

    except NodeUnavailableError as exc:
        return exc.to_dict()
    except NodeExecutionError as exc:
        return exc.to_dict()
    except NodeExternalProcessError as exc:
        return exc.to_dict()
    except NodeFrontendOnlyError as exc:
        return exc.to_dict()
    except NodeSaasCredentialsError as exc:
        return exc.to_dict()
    except Exception as exc:
        return {
            "_execution_error": True,
            "node_id":          node_id,
            "error":            str(exc),
            "exit_code":        -1,
        }


def get_unavailability_report() -> Dict[str, Any]:
    """
    Retourne un rapport complet de disponibilité pour tous les outils Nexus.
    Utilisé par list_pipeline et pipeline_status de Leon.
    """
    checker = NodeAvailabilityChecker()
    report  = checker.full_report()

    return {
        "available_count":   len(report["available"]),
        "unavailable_count": len(report["unavailable"]),
        "external_count":    len(report["external"]),
        "frontend_count":    len(report["frontend"]),
        "saas_count":        len(report["saas"]),
        "available_tools":   [st.name for st in report["available"]],
        "unavailable_tools": [
            {"tool": st.name, "reason": st.reason, "install": st.install}
            for st in report["unavailable"]
        ],
        "external_processes": [
            {
                "tool": st.name,
                "command": TOOL_REGISTRY.get(st.name, {}).get("external_command", ""),
            }
            for st in report["external"]
        ],
        "frontend_only_nodes": [
            nid for st in report["frontend"]
            for nid in TOOL_REGISTRY.get(st.name, {}).get("nodes", [])
        ],
        "saas_required": [
            {
                "tool":    st.name,
                "service": TOOL_REGISTRY.get(st.name, {}).get("service", ""),
                "env_vars": TOOL_REGISTRY.get(st.name, {}).get("env_vars", []),
            }
            for st in report["saas"]
        ],
        "spoken_summary": checker.leon_spoken_report(),
    }
