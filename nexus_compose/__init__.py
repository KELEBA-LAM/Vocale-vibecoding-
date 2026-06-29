"""
nexus_compose
─────────────
NEXUS unified software design pipeline — composability orchestration module.
Le patch anti-stubs est intégré et s'applique automatiquement à l'import.

Quick start
───────────
    from nexus_compose import build_graph, Orchestrator

    G    = build_graph()
    orch = Orchestrator(G)

    # dry-run : inspecter ce qui s'exécuterait (sans stubs silencieux)
    report = orch.dry_run()
    print(report)

    # pipeline greenfield complet
    result = orch.greenfield_pipeline(ctx={"code_path": "/mon/projet"})
    print(result.summary())

    # une seule phase
    result = orch.run_phase("audit", ctx={"target_path": "/mon/projet"})

    # un nœud précis — lève NodeUnavailableError si l'outil est absent
    r = orch.run_node("semgrep.semgrep_scan", {"target_path": "."})

    # tracer un chemin entre deux nœuds
    trace = orch.trace("LEON", "PRODUCTION")
    print(trace.summary())

    # remplacer un handler à la volée
    orch.inject("neo4j.create", mon_handler_neo4j)

Graph introspection
───────────────────
    G.summary()                          # tableau ASCII des statistiques
    G.list_nodes(module="semgrep")       # tous les node_ids semgrep
    G.list_nodes(phase="audit")          # tous les node_ids de la phase audit
    G.reachable_forward("TMDD")          # sous-graphe aval
    G.find_paths("LEON", "PRODUCTION")   # tous les chemins simples
    G.topological_sort()                 # ordre topologique complet
    G.entry_nodes()                      # points d'entrée du pipeline
    G.exit_nodes()                       # points de sortie du pipeline

Patch anti-stubs (intégré)
──────────────────────────
    À l'import de nexus_compose, le patch s'applique automatiquement sur
    ALL_HANDLERS : chaque handler stub est remplacé par une exception typée
    qui décrit précisément pourquoi le nœud est indisponible.

    Accès direct aux utilitaires du patch :
        from nexus_compose import (
            NodeUnavailableError,       # outil binaire / SDK absent
            NodeExecutionError,         # outil présent mais erreur à l'exécution
            NodeExternalProcessError,   # processus long-running requis
            NodeFrontendOnlyError,      # module JavaScript navigateur uniquement
            NodeSaasCredentialsError,   # credentials SaaS / cloud manquants
            NodeAvailabilityChecker,    # vérification proactive des outils
            ExecutionPlan,              # plan d'exécution filtré
            wrap_handler_safe,          # exécution sécurisée d'un handler
            get_unavailability_report,  # rapport complet de disponibilité
            apply_patch,               # réappliquer le patch manuellement
        )

    Exemple — exécution sécurisée sans try/except :
        from nexus_compose import wrap_handler_safe, NodeUnavailableError
        result = wrap_handler_safe("semgrep.semgrep_scan", ctx)
        if result.get("_unavailable"):
            print(result["install"])   # commande d'installation

    Exemple — vérification proactive :
        from nexus_compose import NodeAvailabilityChecker
        checker = NodeAvailabilityChecker()
        checker.raise_if_unavailable("neo4j.create")  # → NodeUnavailableError si absent
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── 1. Couche core nexus_compose ──────────────────────────────────────────────
# Ces imports doivent venir EN PREMIER pour que ALL_HANDLERS soit peuplé
# avant que le patch ne s'y applique.

from .graph import (
    ComposabilityGraph,
    Edge,
    EdgeType,
    Node,
    NodeMeta,
    NodeResult,
)
from .orchestrator import (
    DryRunReport,
    DryRunNode,
    Orchestrator,
    PipelineResult,
    StepRecord,
    TraceResult,
)
from .registry import build as build_graph

# ── 2. Couche patch anti-stubs ────────────────────────────────────────────────
# Importé APRÈS le core pour que drivers.ALL_HANDLERS soit déjà construit.
# Si nexus_compose_patch est absent (installation minimale), on dégrade
# gracieusement avec un avertissement — le pipeline reste fonctionnel
# mais les stubs redeviennent silencieux.

_patch_available: bool = False

try:
    # FIX: imports relatifs — les modules sont dans le meme package (nexus_compose/)
    from .stub_eliminator import (
        apply_patch,
        wrap_handler_safe,
        get_unavailability_report,
    )
    from .node_availability import (
        NodeAvailabilityChecker,
        ExecutionPlan,
    )
    from .exceptions import (
        NodeUnavailableError,
        NodeExecutionError,
        NodeExternalProcessError,
        NodeFrontendOnlyError,
        NodeSaasCredentialsError,
    )

    # Application automatique : ALL_HANDLERS est maintenant peuplé,
    # on peut remplacer les stubs en toute sécurité.
    apply_patch()
    _patch_available = True

except ImportError:
    logger.warning(
        "stub_eliminator / exceptions / node_availability non importables — les stubs silencieux restent actifs. "
        "Vérifier que exceptions.py, stub_eliminator.py, node_availability.py existent dans le package."
    )

    # Fournir des stubs de remplacement no-op pour éviter les ImportError
    # chez les consommateurs qui feraient `from nexus_compose import NodeUnavailableError`.

    class _PatchUnavailable(RuntimeError):
        """Levée quand nexus_compose_patch n'est pas installé."""
        def __init__(self, cls_name: str):
            super().__init__(
                f"{cls_name} n'est pas disponible — installer nexus_compose_patch : "
                "pip install -e nexus_compose_patch/"
            )

    class NodeUnavailableError(Exception):       # type: ignore[no-redef]
        pass

    class NodeExecutionError(Exception):         # type: ignore[no-redef]
        pass

    class NodeExternalProcessError(Exception):   # type: ignore[no-redef]
        pass

    class NodeFrontendOnlyError(Exception):      # type: ignore[no-redef]
        pass

    class NodeSaasCredentialsError(Exception):   # type: ignore[no-redef]
        pass

    class NodeAvailabilityChecker:               # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise _PatchUnavailable("NodeAvailabilityChecker")

    class ExecutionPlan:                         # type: ignore[no-redef]
        def __init__(self, *a, **kw):
            raise _PatchUnavailable("ExecutionPlan")

    def apply_patch() -> int:                   # type: ignore[no-redef]
        logger.warning("apply_patch() no-op — nexus_compose_patch absent")
        return 0

    def wrap_handler_safe(node_id, ctx, handlers=None) -> dict:  # type: ignore[no-redef]
        """Fallback sans patch : exécute directement, sans protection."""
        try:
            from nexus_compose.drivers import ALL_HANDLERS
            h = (handlers or ALL_HANDLERS).get(node_id)
            return h(ctx) if h else {"_error": f"nœud inconnu : {node_id}"}
        except Exception as exc:
            return {"_execution_error": True, "node_id": node_id, "error": str(exc)}

    def get_unavailability_report() -> dict:    # type: ignore[no-redef]
        return {"error": "nexus_compose_patch non installé", "_patch_available": False}


# ── 3. Métadonnées ────────────────────────────────────────────────────────────

__version__       = "1.0.0"
__author__        = "NEXUS / nexus_compose"
__patch_active__  = _patch_available   # True si les stubs sont éliminés

# ── 4. Exports publics ────────────────────────────────────────────────────────

__all__ = [
    # ── Core graph ───────────────────────────────────────────────────────
    "ComposabilityGraph",
    "Edge",
    "EdgeType",
    "Node",
    "NodeMeta",
    "NodeResult",
    # ── Orchestration ────────────────────────────────────────────────────
    "Orchestrator",
    "PipelineResult",
    "StepRecord",
    "DryRunReport",
    "DryRunNode",
    "TraceResult",
    # ── Factory ──────────────────────────────────────────────────────────
    "build_graph",
    # ── Patch anti-stubs — exceptions ────────────────────────────────────
    "NodeUnavailableError",
    "NodeExecutionError",
    "NodeExternalProcessError",
    "NodeFrontendOnlyError",
    "NodeSaasCredentialsError",
    # ── Patch anti-stubs — utilitaires ───────────────────────────────────
    "NodeAvailabilityChecker",
    "ExecutionPlan",
    "apply_patch",
    "wrap_handler_safe",
    "get_unavailability_report",
    # ── Métadonnées ───────────────────────────────────────────────────────
    "__version__",
    "__patch_active__",
]
