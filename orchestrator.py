"""
nexus_compose.orchestrator
──────────────────────────
Main execution engine for the NEXUS composability graph.

Public API
──────────
Orchestrator(graph)

    .run_node(node_id, ctx)          → NodeResult
    .run_pipeline(node_ids, ctx)     → PipelineResult
    .run_phase(phase, ctx)           → PipelineResult
    .run_from(entry, ctx, **opts)    → PipelineResult
    .dry_run(node_ids)               → DryRunReport
    .trace(source, target, ctx)      → TraceResult
    .run_parallel(node_ids, ctx)     → PipelineResult
    .inject(node_id, handler)        → None

All executions propagate context: each node's output dict is merged into
the shared context before the next node runs.  Errors are captured without
aborting (fail_fast=False by default).
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .graph import (
    ComposabilityGraph, EdgeType, Node, NodeResult
)

logger = logging.getLogger(__name__)


# ── Result containers ──────────────────────────────────────────────────────────

@dataclass
class StepRecord:
    node_id:     str
    success:     bool
    duration_ms: float
    data:        Any            = None
    error:       Optional[str] = None


@dataclass
class PipelineResult:
    steps:       List[StepRecord]       = field(default_factory=list)
    context:     Dict[str, Any]         = field(default_factory=dict)
    success:     bool                   = True
    total_ms:    float                  = 0.0
    errors:      List[Tuple[str, str]]  = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.success

    def summary(self) -> str:
        ok  = sum(1 for s in self.steps if s.success)
        nok = len(self.steps) - ok
        lines = [
            f"Pipeline: {len(self.steps)} steps | ✓ {ok} | ✗ {nok} | {self.total_ms:.0f} ms",
        ]
        for rec in self.steps:
            icon = "✓" if rec.success else "✗"
            err  = f"  → {rec.error}" if rec.error else ""
            lines.append(f"  {icon} [{rec.duration_ms:5.0f}ms]  {rec.node_id}{err}")
        return "\n".join(lines)


@dataclass
class DryRunNode:
    node_id:  str
    module:   str
    function: str
    phase:    str
    live:     bool
    io_in:    str
    io_out:   str
    in_edges: List[str]
    out_edges: List[str]


@dataclass
class DryRunReport:
    nodes:      List[DryRunNode]
    live_count: int
    stub_count: int

    def __str__(self) -> str:
        lines = [
            f"Dry-run: {len(self.nodes)} nodes | {self.live_count} live | {self.stub_count} stub",
            "",
        ]
        current_phase = None
        for n in self.nodes:
            if n.phase != current_phase:
                current_phase = n.phase
                lines.append(f"  ── phase: {n.phase} ──")
            live = "●" if n.live else "○"
            lines.append(
                f"  {live}  {n.node_id:42s}  {n.io_in[:28]:28s} → {n.io_out[:28]}"
            )
        return "\n".join(lines)


@dataclass
class TraceResult:
    path:     List[str]
    steps:    List[StepRecord] = field(default_factory=list)
    context:  Dict[str, Any]   = field(default_factory=dict)
    found:    bool             = True

    def summary(self) -> str:
        if not self.found:
            return f"No path found: {' → '.join(self.path[:2] or ['?','?'])}"
        pr = PipelineResult(steps=self.steps, context=self.context)
        return f"Trace {' → '.join(self.path)}\n{pr.summary()}"


# ── Orchestrator ───────────────────────────────────────────────────────────────

class Orchestrator:
    """
    Execute nodes and pipelines over the ComposabilityGraph.
    """

    def __init__(
        self,
        graph:        ComposabilityGraph,
        fail_fast:    bool = False,
        max_workers:  int  = 8,
        on_step_done: Optional[Callable[[StepRecord], None]] = None,
    ):
        self.G            = graph
        self.fail_fast    = fail_fast
        self.max_workers  = max_workers
        self.on_step_done = on_step_done   # optional hook after every step

    # ── single node ────────────────────────────────────────────────────────────

    def run_node(self, node_id: str, ctx: Dict[str, Any]) -> NodeResult:
        """Execute one node and return its NodeResult."""
        node   = self.G.node(node_id)
        t0     = time.monotonic()
        result = node(ctx)
        dt     = (time.monotonic() - t0) * 1000
        level  = logging.DEBUG if result.success else logging.WARNING
        logger.log(level, "[%s] %.0f ms  success=%s", node_id, dt, result.success)
        return result

    # ── ordered pipeline ───────────────────────────────────────────────────────

    def run_pipeline(
        self,
        node_ids:  List[str],
        ctx:       Dict[str, Any] | None = None,
        fail_fast: bool | None           = None,
    ) -> PipelineResult:
        """
        Execute nodes sequentially in the given order.
        Each successful node's output dict is merged into ctx before the
        next node runs.
        """
        ctx       = dict(ctx or {})
        fast      = self.fail_fast if fail_fast is None else fail_fast
        pr        = PipelineResult(context=ctx)
        wall_t0   = time.monotonic()

        for nid in node_ids:
            t0     = time.monotonic()
            result = self.run_node(nid, ctx)
            dt     = (time.monotonic() - t0) * 1000

            rec = StepRecord(
                node_id     = nid,
                success     = result.success,
                duration_ms = dt,
                data        = result.data,
                error       = result.error,
            )
            pr.steps.append(rec)

            if self.on_step_done:
                self.on_step_done(rec)

            if result.success and isinstance(result.data, dict):
                ctx.update(result.data)

            if not result.success:
                pr.errors.append((nid, result.error or "unknown error"))
                pr.success = False
                if fast:
                    logger.warning("fail_fast: stopping pipeline after %s", nid)
                    break

        pr.context  = ctx
        pr.total_ms = (time.monotonic() - wall_t0) * 1000
        return pr

    # ── phase ──────────────────────────────────────────────────────────────────

    def run_phase(
        self,
        phase: str,
        ctx:   Dict[str, Any] | None = None,
    ) -> PipelineResult:
        """
        Run all nodes belonging to a phase in topological order.
        """
        phase_ids = [n.meta.id for n in self.G.nodes(phase=phase)]
        if not phase_ids:
            raise ValueError(f"No nodes found for phase {phase!r}")
        ordered = self.G.topological_sort(phase_ids)
        logger.info("run_phase(%s): %d nodes", phase, len(ordered))
        return self.run_pipeline(ordered, ctx)

    # ── forward traversal from entry point ─────────────────────────────────────

    def run_from(
        self,
        entry_id:    str,
        ctx:         Dict[str, Any] | None = None,
        max_nodes:   int  = 200,
        edge_filter: Optional[Callable[["Edge"], bool]] = None,  # type: ignore[name-defined]
    ) -> PipelineResult:
        """
        BFS from entry_id over the composability graph, executing each
        reachable node in topological order.

        edge_filter(edge) → bool  lets you restrict to certain EdgeTypes.
        Example:  edge_filter=lambda e: e.type in {EdgeType.DATA_FLOW, EdgeType.TRANSFORM}
        """
        reachable = self.G.reachable_forward(entry_id)
        if len(reachable) > max_nodes:
            logger.warning(
                "run_from: reachable set has %d nodes (max_nodes=%d), truncating",
                len(reachable), max_nodes,
            )
            reachable = set(list(reachable)[:max_nodes])

        ordered = self.G.topological_sort(list(reachable))
        # respect edge_filter by removing nodes that aren't reachable via
        # accepted edge types
        if edge_filter:
            allowed: set[str] = {entry_id}
            for nid in ordered:
                for pred_edge in self.G.predecessors(nid):
                    if pred_edge.source in allowed and edge_filter(pred_edge):
                        allowed.add(nid)
                        break
            ordered = [n for n in ordered if n in allowed]

        logger.info("run_from(%s): %d nodes", entry_id, len(ordered))
        return self.run_pipeline(ordered, ctx)

    # ── parallel execution ─────────────────────────────────────────────────────

    def run_parallel(
        self,
        node_ids: List[str],
        ctx:      Dict[str, Any] | None = None,
    ) -> PipelineResult:
        """
        Execute a set of *independent* nodes in parallel (ThreadPoolExecutor).
        All nodes receive the same input ctx; outputs are merged at the end.
        Use only for nodes that have no data-flow dependency between them.
        """
        ctx     = dict(ctx or {})
        pr      = PipelineResult(context=ctx)
        wall_t0 = time.monotonic()
        futures = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for nid in node_ids:
                futures[pool.submit(self.run_node, nid, dict(ctx))] = nid

            for future in as_completed(futures):
                nid    = futures[future]
                t0_loc = time.monotonic()
                try:
                    result = future.result()
                except Exception as exc:
                    result = NodeResult(node_id=nid, success=False, error=str(exc))

                dt  = (time.monotonic() - t0_loc) * 1000
                rec = StepRecord(
                    node_id     = nid,
                    success     = result.success,
                    duration_ms = dt,
                    data        = result.data,
                    error       = result.error,
                )
                pr.steps.append(rec)
                if self.on_step_done:
                    self.on_step_done(rec)

                if result.success and isinstance(result.data, dict):
                    ctx.update(result.data)
                else:
                    pr.success = False
                    pr.errors.append((nid, result.error or "error"))

        pr.context  = ctx
        pr.total_ms = (time.monotonic() - wall_t0) * 1000
        return pr

    # ── trace (source → target) ────────────────────────────────────────────────

    def trace(
        self,
        source:  str,
        target:  str,
        ctx:     Dict[str, Any] | None = None,
    ) -> TraceResult:
        """
        Find the shortest path from source to target and execute every node
        along it.
        """
        path = self.G.shortest_path(source, target)
        if not path:
            logger.warning("trace: no path from %s to %s", source, target)
            return TraceResult(path=[source, target], found=False)

        pr = self.run_pipeline(path, ctx)
        return TraceResult(
            path    = path,
            steps   = pr.steps,
            context = pr.context,
            found   = True,
        )

    # ── dry run ────────────────────────────────────────────────────────────────

    def dry_run(self, node_ids: Optional[List[str]] = None) -> DryRunReport:
        """
        Report what would run without executing anything.
        Returned nodes are in topological order.
        """
        ids     = node_ids or self.G.list_nodes()
        ordered = self.G.topological_sort(ids)
        records: List[DryRunNode] = []

        for nid in ordered:
            n = self.G.node(nid)
            records.append(DryRunNode(
                node_id   = nid,
                module    = n.meta.module,
                function  = n.meta.function,
                phase     = n.meta.phase,
                live      = n.is_live,
                io_in     = n.meta.io_in,
                io_out    = n.meta.io_out,
                in_edges  = [e.source for e in self.G.predecessors(nid)],
                out_edges  = [e.target for e in self.G.successors(nid)],
            ))

        live  = sum(1 for r in records if r.live)
        stub  = len(records) - live
        return DryRunReport(nodes=records, live_count=live, stub_count=stub)

    # ── injection (hot-replace a handler at runtime) ───────────────────────────

    def inject(self, node_id: str, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Replace a stub handler with a live implementation at runtime."""
        self.G.node(node_id).replace_handler(handler)
        logger.info("Injected live handler into %s", node_id)

    # ── convenience iterators ──────────────────────────────────────────────────

    def iter_phase_pipelines(
        self,
        ctx: Dict[str, Any] | None = None,
    ) -> Iterator[Tuple[str, PipelineResult]]:
        """Yield (phase_name, PipelineResult) for each phase in pipeline order."""
        _PHASE_ORDER = [
            "elicit", "arch", "net", "policy",
            "threat", "graph", "codegen", "audit", "report", "deploy",
        ]
        shared_ctx = dict(ctx or {})
        for phase in _PHASE_ORDER:
            try:
                pr = self.run_phase(phase, shared_ctx)
                shared_ctx.update(pr.context)
                yield phase, pr
            except ValueError:
                # phase has no nodes — skip silently
                continue

    # ── standard pipeline presets ──────────────────────────────────────────────

    def greenfield_pipeline(self, ctx: Dict[str, Any] | None = None) -> PipelineResult:
        """
        Full greenfield run: LEON → Q2D → LikeC4 → C4IF → Containerlab →
        OPA/Batfish → Threat Dragon → pytm → Neo4j → TMDD → code gen →
        Semgrep/Bearer/CodeQL → REPORT → PRODUCTION.
        """
        entry = "LEON"
        return self.run_from(entry, ctx)

    def audit_only_pipeline(
        self,
        code_path: str,
        ctx:       Dict[str, Any] | None = None,
    ) -> PipelineResult:
        """
        Audit an existing codebase — skip architecture/threat modelling phases.
        CODEBASE → Semgrep + Bearer + CodeQL → Neo4j → REPORT
        """
        base_ctx = dict(ctx or {}, code_path=code_path, target_path=code_path)
        node_ids = [
            "CODEBASE",
            "semgrep.semgrep_scan",
            "bearer.bearer_scan",
            "bearer.rapport_privacy",
            "bearer.export_sarif",
            "codeql.codeql_database_create",
            "codeql.codeql_database_analyze",
            "codeql.suite_security_extended_qls_",
            "codeql.suite_security_and_quality_q",
            "semgrep.semgrep_scan_sca",
            "neo4j.create",
            "REPORT",
        ]
        return self.run_pipeline(node_ids, base_ctx)

    def threat_model_pipeline(
        self,
        architecture_json: dict,
        ctx: Dict[str, Any] | None = None,
    ) -> PipelineResult:
        """
        Threat-modelling-only pipeline from an existing C4 architecture dict.
        likec4_export_json → pytm → TD → Neo4j → TMDD → constraint injection
        """
        base_ctx = dict(ctx or {}, architecture=architecture_json)
        node_ids = [
            "likec4.likec4_export_json",
            "pytm.tm_process",
            "pytm.tm_resolve",
            "pytm.json",
            "pytm.tm_dfd",
            "pytm.tm_report",
            "td.threatmodelcontroller_create",
            "td.editeur_de_diagramme_x6_form",
            "td.stride_js",
            "td.linddun_js",
            "td.cia_js",
            "neo4j.create",
            "tmdd.tmdd_init",
            "tmdd.tmdd_feature",
            "tmdd.tmdd_lint",
            "tmdd.tmdd_compile",
            "tmdd.generate_agent_prompt",
            "REPORT",
        ]
        return self.run_pipeline(node_ids, base_ctx)

    def network_validation_pipeline(
        self,
        topology_file: str,
        policy_file:   str,
        ctx: Dict[str, Any] | None = None,
    ) -> PipelineResult:
        """
        Network-only validation: Containerlab → Batfish → OPA policy eval.
        """
        base_ctx = dict(ctx or {}, topology=topology_file, policy=policy_file)
        node_ids = [
            "clab.clab_generate",
            "clab.clab_deploy",
            "clab.clab_save",
            "clab.clab_graph",
            "bf.bfq_testfilters",
            "bf.bfq_routes",
            "bf.bfq_bgpedges",
            "bf.bfq_ipowners",
            "bf.bfq_unusedstructures",
            "bf.bfq_undefinedreferences",
            "bf.bfq_initissues",
            "bf.bfq_ipsecsessionstatus",
            "opa.opa_eval",
            "neo4j.create",
            "REPORT",
        ]
        return self.run_pipeline(node_ids, base_ctx)
