"""
nexus_compose
─────────────
NEXUS unified software design pipeline — composability orchestration module.

Quick start
───────────
    from nexus_compose import build_graph, Orchestrator

    G   = build_graph()
    orch = Orchestrator(G)

    # dry-run: inspect what would execute
    report = orch.dry_run()
    print(report)

    # run the full greenfield pipeline (all stubs by default)
    result = orch.greenfield_pipeline(ctx={"code_path": "/my/project"})
    print(result.summary())

    # run just one phase
    result = orch.run_phase("audit", ctx={"target_path": "/my/project"})

    # run a specific node
    r = orch.run_node("semgrep.semgrep_scan", {"target_path": "."})

    # trace a path between two nodes
    trace = orch.trace("LEON", "PRODUCTION")
    print(trace.summary())

    # replace a stub with a live handler at runtime
    orch.inject("neo4j.create", my_live_neo4j_handler)

Graph introspection
───────────────────
    G.summary()                          # ascii stats table
    G.list_nodes(module="semgrep")       # all semgrep node ids
    G.list_nodes(phase="audit")          # all audit-phase node ids
    G.reachable_forward("TMDD")          # downstream subgraph
    G.find_paths("LEON", "PRODUCTION")   # all simple paths
    G.topological_sort()                 # full topo order
    G.entry_nodes()                      # pipeline entry points
    G.exit_nodes()                       # pipeline exit points
"""

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

__all__ = [
    # graph layer
    "ComposabilityGraph",
    "Edge",
    "EdgeType",
    "Node",
    "NodeMeta",
    "NodeResult",
    # orchestration layer
    "Orchestrator",
    "PipelineResult",
    "StepRecord",
    "DryRunReport",
    "DryRunNode",
    "TraceResult",
    # factory
    "build_graph",
]

__version__ = "1.0.0"
__author__  = "NEXUS / nexus_compose"
