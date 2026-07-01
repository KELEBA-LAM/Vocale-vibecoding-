"""
tests/test_nexus_compose.py
───────────────────────────
Test suite for nexus_compose.

Run:
    cd /home/claude/work
    python -m pytest tests/ -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from nexus_compose import (
    build_graph, Orchestrator,
    EdgeType, NodeResult, PipelineResult,
)
from nexus_compose.graph import ComposabilityGraph


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def G() -> ComposabilityGraph:
    return build_graph()


@pytest.fixture(scope="session")
def orch(G) -> Orchestrator:
    return Orchestrator(G, fail_fast=False)


# ══════════════════════════════════════════════════════════════════════════════
#  1. GRAPH INTEGRITY
# ══════════════════════════════════════════════════════════════════════════════

class TestGraphIntegrity:

    def test_node_count(self, G):
        # 164 parsed nodes (163 tool nodes + codegen.unified_system) + 5 virtual
        assert G.node_count == 169, f"Expected 169 nodes, got {G.node_count}"

    def test_edge_count(self, G):
        # 216 original edges + 2 new (tmdd.generate_agent_prompt→codegen.unified_system,
        # codegen.unified_system→CODE_GENERATED)
        assert G.edge_count == 218, f"Expected 218 edges, got {G.edge_count}"

    def test_virtual_nodes_present(self, G):
        for vid in ["LEON", "CODEBASE", "CODE_GENERATED", "REPORT", "PRODUCTION"]:
            assert G.node(vid) is not None, f"Virtual node {vid} missing"

    def test_all_modules_present(self, G):
        expected = {"q2d","likec4","c4if","struct","clab","opa","bf",
                    "td","pytm","neo4j","tmdd","semgrep","bearer","codeql",
                    "codegen","virtual"}
        found = {n.meta.module for n in G.nodes()}
        assert expected <= found, f"Missing modules: {expected - found}"

    def test_no_self_loops(self, G):
        bad = [(e.source, e.target) for e in G.edges() if e.source == e.target]
        assert not bad, f"Self-loops found: {bad}"

    def test_all_edge_types_present(self, G):
        used = {e.type for e in G.edges()}
        for et in EdgeType:
            assert et in used, f"EdgeType {et} unused — check edge catalogue"

    def test_entry_nodes(self, G):
        entries = G.entry_nodes()
        assert "LEON"     in entries, "LEON should be an entry node"
        assert "CODEBASE" in entries, "CODEBASE should be an entry node"

    def test_exit_nodes(self, G):
        exits = G.exit_nodes()
        assert "PRODUCTION" in exits, "PRODUCTION should be an exit node"

    def test_production_reachable_from_leon(self, G):
        reach = G.reachable_forward("LEON")
        assert "PRODUCTION" in reach, "PRODUCTION must be reachable from LEON"

    def test_report_reachable_from_codebase(self, G):
        reach = G.reachable_forward("CODEBASE")
        assert "REPORT" in reach

    def test_no_dangling_edges(self, G):
        """All edge endpoints must reference registered nodes."""
        node_ids = set(G.list_nodes())
        for e in G.edges():
            assert e.source in node_ids, f"Edge source {e.source!r} not a node"
            assert e.target in node_ids, f"Edge target {e.target!r} not a node"

    def test_topo_sort_covers_all_nodes(self, G):
        topo = G.topological_sort()
        assert len(topo) == G.node_count

    def test_predecessor_successor_symmetry(self, G):
        """For every edge, target must list source as predecessor."""
        for e in G.edges():
            preds = [p.source for p in G.predecessors(e.target)]
            assert e.source in preds

    def test_summary_contains_all_modules(self, G):
        s = G.summary()
        for mod in ["semgrep","bearer","codeql","neo4j","tmdd","opa"]:
            assert mod in s


# ══════════════════════════════════════════════════════════════════════════════
#  2. NODE METADATA
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeMeta:

    def test_all_nodes_have_id(self, G):
        for n in G.nodes():
            assert n.meta.id

    def test_all_nodes_have_phase(self, G):
        missing = [n.meta.id for n in G.nodes() if not n.meta.phase]
        assert not missing, f"Nodes missing phase: {missing[:5]}"

    def test_all_nodes_have_module(self, G):
        missing = [n.meta.id for n in G.nodes() if not n.meta.module]
        assert not missing

    def test_virtual_nodes_flagged(self, G):
        for vid in ["LEON","CODEBASE","CODE_GENERATED","REPORT","PRODUCTION"]:
            assert G.node(vid).meta.virtual is True

    def test_real_nodes_not_virtual(self, G):
        # 163 tool nodes + 1 codegen.unified_system bridge = 164 real nodes
        real = [n for n in G.nodes() if not n.meta.virtual]
        assert len(real) == 164

    def test_node_io_fields_present(self, G):
        empty_io = [n.meta.id for n in G.nodes()
                    if not n.meta.io_in and not n.meta.io_out and not n.meta.virtual]
        assert len(empty_io) == 0, f"Real nodes missing io: {empty_io[:5]}"


# ══════════════════════════════════════════════════════════════════════════════
#  3. STUB EXECUTION (no external tools required)
# ══════════════════════════════════════════════════════════════════════════════

class TestStubExecution:

    def test_run_node_returns_node_result(self, orch):
        r = orch.run_node("LEON", {"text": "hello"})
        assert isinstance(r, NodeResult)

    def test_stub_node_returns_stub_marker(self, orch):
        r = orch.run_node("neo4j.match_return", {"cypher": "MATCH (n) RETURN n LIMIT 1"})
        # neo4j is stub if driver not installed — either success (live) or stub
        assert isinstance(r, NodeResult)

    def test_all_virtual_nodes_run(self, orch):
        for vid in ["LEON","CODEBASE","CODE_GENERATED","REPORT","PRODUCTION"]:
            r = orch.run_node(vid, {"text": "test", "code_path": "."})
            assert isinstance(r, NodeResult)

    def test_pipeline_returns_pipeline_result(self, orch):
        ids = ["LEON", "q2d.generate", "q2d.fix_format"]
        pr  = orch.run_pipeline(ids, {})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) == 3

    def test_pipeline_merges_context(self, orch):
        """Stub output dicts should be merged into context between steps."""
        ids = ["CODEBASE", "semgrep.semgrep_scan"]
        pr  = orch.run_pipeline(ids, {"code_path": ".", "target_path": "."})
        assert isinstance(pr.context, dict)

    def test_dry_run_covers_all_nodes(self, orch):
        report = orch.dry_run()
        assert len(report.nodes) == 169
        assert report.live_count + report.stub_count == 169

    def test_dry_run_phase_filter(self, orch):
        report = orch.dry_run(orch.G.list_nodes(phase="audit"))
        phases = {n.phase for n in report.nodes}
        assert phases == {"audit"}

    def test_dry_run_str_contains_nodes(self, orch):
        s = str(orch.dry_run())
        assert "semgrep" in s
        assert "bearer"  in s

    def test_run_phase_audit(self, orch):
        pr = orch.run_phase("audit", {"target_path": ".", "code_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) > 0

    def test_run_phase_unknown_raises(self, orch):
        with pytest.raises(ValueError):
            orch.run_phase("nonexistent_phase_xyz")


# ══════════════════════════════════════════════════════════════════════════════
#  4. TOPOLOGY & PATH FINDING
# ══════════════════════════════════════════════════════════════════════════════

class TestTopology:

    def test_shortest_path_leon_to_production(self, G):
        path = G.shortest_path("LEON", "PRODUCTION")
        assert path is not None
        assert path[0]  == "LEON"
        assert path[-1] == "PRODUCTION"
        assert len(path) >= 3

    def test_find_paths_multiple(self, G):
        paths = G.find_paths("CODEBASE", "neo4j.create", max_paths=3)
        assert len(paths) >= 1

    def test_backward_reachability(self, G):
        """PRODUCTION must be reachable backward to TMDD."""
        back = G.reachable_backward("PRODUCTION")
        assert "tmdd.generate_agent_prompt" in back
        assert "LEON" in back

    def test_neighborhood(self, G):
        nb = G.neighborhood("neo4j.create")
        assert "neo4j.match_return" in nb
        assert "semgrep.semgrep_scan" in nb   # semgrep stores to neo4j

    def test_topo_sort_order(self, G):
        """LEON must come before q2d nodes in topo sort."""
        topo = G.topological_sort(["LEON","q2d.generate","q2d.fix_format"])
        assert topo.index("LEON") < topo.index("q2d.generate")

    def test_entry_points(self, G):
        entries = G.entry_nodes()
        for eid in entries:
            assert not G.predecessors(eid)

    def test_exit_points(self, G):
        exits = G.exit_nodes()
        for eid in exits:
            assert not G.successors(eid)


# ══════════════════════════════════════════════════════════════════════════════
#  5. ORCHESTRATOR TRACE
# ══════════════════════════════════════════════════════════════════════════════

class TestTrace:

    def test_trace_found(self, orch):
        t = orch.trace("LEON", "q2d.generate")
        assert t.found
        assert "LEON" in t.path
        assert "q2d.generate" in t.path

    def test_trace_no_path(self, orch):
        # PRODUCTION has no outgoing edges → can't reach LEON from it
        t = orch.trace("PRODUCTION", "LEON")
        assert not t.found

    def test_trace_summary_str(self, orch):
        t = orch.trace("CODEBASE", "semgrep.semgrep_scan")
        s = t.summary()
        assert "CODEBASE" in s or "semgrep" in s


# ══════════════════════════════════════════════════════════════════════════════
#  6. INJECTION
# ══════════════════════════════════════════════════════════════════════════════

class TestInjection:

    def test_inject_replaces_stub(self, orch, G):
        sentinel = {"injected": True, "value": 42}
        orch.inject("REPORT", lambda ctx: sentinel)
        r = orch.run_node("REPORT", {})
        assert r.success
        assert r.data == sentinel
        # restore stub
        G.node("REPORT").replace_handler(None)

    def test_inject_bad_node_raises(self, orch):
        with pytest.raises(KeyError):
            orch.inject("nonexistent.node", lambda ctx: {})


# ══════════════════════════════════════════════════════════════════════════════
#  7. PRESET PIPELINES (stub-safe)
# ══════════════════════════════════════════════════════════════════════════════

class TestPresets:

    def test_audit_only_pipeline(self, orch):
        pr = orch.audit_only_pipeline(".", {"target_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) > 0

    def test_threat_model_pipeline(self, orch):
        pr = orch.threat_model_pipeline({"elements": [], "relationships": []})
        assert isinstance(pr, PipelineResult)

    def test_network_validation_pipeline(self, orch):
        pr = orch.network_validation_pipeline("topology.yml", "policy.rego")
        assert isinstance(pr, PipelineResult)

    def test_iter_phase_pipelines(self, orch):
        phases_run = []
        for phase, pr in orch.iter_phase_pipelines():
            assert isinstance(pr, PipelineResult)
            phases_run.append(phase)
        assert len(phases_run) > 0
        # verify canonical order
        order = ["elicit","arch","net","policy","threat","graph","codegen","audit","report","deploy"]
        for a, b in zip(phases_run, order):
            assert a == b


# ══════════════════════════════════════════════════════════════════════════════
#  8. PARALLEL EXECUTION
# ══════════════════════════════════════════════════════════════════════════════

class TestParallel:

    def test_parallel_independent_nodes(self, orch):
        # Bearer scan, CodeQL pack install, Semgrep schema — no data deps
        ids = [
            "bearer.bearer_scan",
            "codeql.codeql_pack_download_install",
            "semgrep.get_semgrep_rule_schema",
        ]
        pr = orch.run_parallel(ids, {"target_path": ".", "code_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) == 3

    def test_parallel_result_has_all_steps(self, orch):
        ids = ["LEON", "CODEBASE"]
        pr  = orch.run_parallel(ids, {"text": "test"})
        executed = {s.node_id for s in pr.steps}
        assert executed == set(ids)


# ══════════════════════════════════════════════════════════════════════════════
#  9. EDGE SEMANTICS
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeSemantics:

    def test_inject_edges_from_tmdd(self, G):
        inject_targets = {
            e.target for e in G.successors("tmdd.generate_agent_prompt")
            if e.type == EdgeType.INJECT
        }
        assert "CODE_GENERATED" in inject_targets
        assert "semgrep.write_custom_semgrep_rule" in inject_targets

    def test_store_edges_reach_neo4j(self, G):
        store_targets = {
            e.target for e in G.edges(etype=EdgeType.STORE)
        }
        assert "neo4j.create" in store_targets

    def test_analyze_edges_from_codeql(self, G):
        analyze_targets = {
            e.target for e in G.successors("codeql.codeql_database_analyze")
            if e.type == EdgeType.ANALYZE
        }
        assert len(analyze_targets) == 3

    def test_indirect_edges_exist(self, G):
        indirect = list(G.edges(etype=EdgeType.INDIRECT))
        assert len(indirect) >= 3

    def test_report_edges_reach_report_node(self, G):
        report_tgts = {e.target for e in G.edges(etype=EdgeType.REPORT)}
        assert "REPORT" in report_tgts
