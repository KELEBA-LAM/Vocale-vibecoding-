"""
test/test_nexus_compose_v2.py
──────────────────────────────
Suite de tests unitaires étendue pour nexus_compose.

Contexte : exécutée contre nexus_compose/registry.py après le correctif qui
enregistre le nœud "codegen.unified_system" (voir EXTRA_DEFS dans registry.py).
Sans ce correctif, TestPresets::test_codegen_pipeline et
TestPresets::test_threat_model_pipeline échouent avec
KeyError: 'codegen.unified_system' — couvert explicitement par TestRegressions.

Apports vs test_nexus_compose.py (original) :
  • Comptages de nœuds/arêtes DYNAMIQUES (seuils), plus un test "drift
    detector" unique et clairement commenté pour la valeur exacte.
  • TestRegressions : verrouille le bug codegen.unified_system pour de bon.
  • fail_fast / on_step_done / parallélisme testés sur un graphe isolé
    déterministe (make_minimal_graph) — indépendant des binaires installés.
  • 60+ nouveaux tests : exceptions, node_availability (API réelle —
    full_report() renvoie des listes par catégorie, execution_plan() prend
    des node_ids, pas un graphe), Edge.apply, NodeResult.raise_if_failed…

Run :
    cd /path/to/Vocale-vibecoding-
    python -m pytest test/test_nexus_compose_v2.py -v
"""

from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from nexus_compose import build_graph, Orchestrator, EdgeType, NodeResult, PipelineResult
from nexus_compose.graph import ComposabilityGraph, Node, Edge, NodeMeta, NodeResult
from nexus_compose.orchestrator import DryRunReport, TraceResult
from nexus_compose.exceptions import (
    NexusNodeError,
    NodeUnavailableError,
    NodeExecutionError,
    NodeExternalProcessError,
    NodeFrontendOnlyError,
    NodeSaasCredentialsError,
)
from nexus_compose.node_availability import NodeAvailabilityChecker, ExecutionPlan, ToolStatus
import nexus_compose.node_availability as node_availability_module


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def G() -> ComposabilityGraph:
    return build_graph()


@pytest.fixture(scope="session")
def orch(G) -> Orchestrator:
    return Orchestrator(G, fail_fast=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_minimal_graph() -> ComposabilityGraph:
    """Mini graphe isolé pour tests unitaires sans dépendance au registre."""
    g = ComposabilityGraph()
    for nid, phase, module in [
        ("A", "elicit", "q2d"),
        ("B", "arch",   "likec4"),
        ("C", "audit",  "semgrep"),
    ]:
        meta = NodeMeta(
            id=nid, module=module, module_name=module.upper(),
            function=f"fn_{nid}", description=f"Node {nid}",
            tag="test", phase=phase, type="tool",
            io_in="any", io_out="any", ref="", virtual=False,
        )
        g.register(Node(meta))
    g.connect(Edge("A", "B", "a→b", EdgeType.DATA_FLOW))
    g.connect(Edge("B", "C", "b→c", EdgeType.TRANSFORM))
    return g


# ══════════════════════════════════════════════════════════════════════════════
# 1. INTÉGRITÉ DU GRAPHE (corrigée : comptages dynamiques)
# ══════════════════════════════════════════════════════════════════════════════

class TestGraphIntegrity:

    def test_node_count_positive(self, G):
        """Le graphe doit avoir au moins 150 nœuds (tolérant aux évolutions)."""
        assert G.node_count >= 150, f"Trop peu de nœuds : {G.node_count}"

    def test_edge_count_positive(self, G):
        """Le graphe doit avoir au moins 180 arêtes."""
        assert G.edge_count >= 180, f"Trop peu d'arêtes : {G.edge_count}"

    def test_graph_stats_consistent(self, G):
        """node_count et edge_count doivent être cohérents avec les structures internes."""
        all_nodes = list(G.nodes())
        all_edges = list(G.edges())
        assert G.node_count == len(all_nodes)
        assert G.edge_count == len(all_edges)

    def test_virtual_nodes_present(self, G):
        for vid in ["LEON", "CODEBASE", "CODE_GENERATED", "REPORT", "PRODUCTION"]:
            assert G.node(vid) is not None, f"Nœud virtuel {vid} manquant"

    def test_exactly_five_virtual_nodes(self, G):
        virtual = [n for n in G.nodes() if n.meta.virtual]
        assert len(virtual) == 5, f"Attendu 5 nœuds virtuels, obtenu {len(virtual)}"

    def test_graph_size_drift_detector(self, G):
        """
        Valeur exacte après homogénéisation des fichiers uploadés (2026-07-01) :
          • nodes.json : 164 nœuds (163 outils tiers + 1 codegen.unified_system)
          • VIRTUAL_DEFS : 5 nœuds (LEON, CODEBASE, CODE_GENERATED, REPORT, PRODUCTION)
          • EDGE_CATALOGUE : 218 arêtes
          → Total : 169 nœuds, 218 arêtes.

        codegen.unified_system est dans nodes.json (module="codegen") —
        plus dans EXTRA_DEFS. registry.py utilise `all_raw = VIRTUAL_DEFS + raw_nodes`.

        Si ce test échoue après un changement DÉLIBÉRÉ, mettez à jour
        les deux constantes ci-dessous dans le même commit.
        """
        EXPECTED_NODE_COUNT = 169
        EXPECTED_EDGE_COUNT = 218
        assert G.node_count == EXPECTED_NODE_COUNT, (
            f"node_count a dérivé : attendu {EXPECTED_NODE_COUNT}, obtenu {G.node_count}. "
            "Si ce changement est voulu, mettez à jour EXPECTED_NODE_COUNT."
        )
        assert G.edge_count == EXPECTED_EDGE_COUNT, (
            f"edge_count a dérivé : attendu {EXPECTED_EDGE_COUNT}, obtenu {G.edge_count}. "
            "Si ce changement est voulu, mettez à jour EXPECTED_EDGE_COUNT."
        )
        assert G.node_count == EXPECTED_NODE_COUNT, (
            f"node_count a dérivé : attendu {EXPECTED_NODE_COUNT}, obtenu {G.node_count}. "
            "Si ce changement est voulu, mettez à jour EXPECTED_NODE_COUNT."
        )
        assert G.edge_count == EXPECTED_EDGE_COUNT, (
            f"edge_count a dérivé : attendu {EXPECTED_EDGE_COUNT}, obtenu {G.edge_count}. "
            "Si ce changement est voulu, mettez à jour EXPECTED_EDGE_COUNT."
        )

    def test_real_node_count(self, G):
        real = [n for n in G.nodes() if not n.meta.virtual]
        # cohérence : total = réels + 5 virtuels
        assert len(real) == G.node_count - 5

    def test_all_modules_present(self, G):
        # "codegen" ajouté car codegen.unified_system est maintenant dans nodes.json
        # (module="codegen") — plus dans EXTRA_DEFS.
        expected = {"q2d", "likec4", "c4if", "struct", "clab", "opa", "bf",
                    "td", "pytm", "neo4j", "tmdd", "semgrep", "bearer", "codeql",
                    "codegen", "virtual"}
        found = {n.meta.module for n in G.nodes()}
        assert expected <= found, f"Modules manquants : {expected - found}"

    def test_no_self_loops(self, G):
        bad = [(e.source, e.target) for e in G.edges() if e.source == e.target]
        assert not bad, f"Boucles sur soi détectées : {bad}"

    def test_all_edge_types_present(self, G):
        used = {e.type for e in G.edges()}
        for et in EdgeType:
            assert et in used, f"EdgeType {et} non utilisé"

    def test_entry_nodes_include_leon_and_codebase(self, G):
        entries = G.entry_nodes()
        assert "LEON" in entries
        assert "CODEBASE" in entries

    def test_exit_nodes_include_production(self, G):
        exits = G.exit_nodes()
        assert "PRODUCTION" in exits

    def test_production_reachable_from_leon(self, G):
        assert "PRODUCTION" in G.reachable_forward("LEON")

    def test_report_reachable_from_codebase(self, G):
        assert "REPORT" in G.reachable_forward("CODEBASE")

    def test_no_dangling_edges(self, G):
        node_ids = set(G.list_nodes())
        for e in G.edges():
            assert e.source in node_ids, f"Source inconnue : {e.source!r}"
            assert e.target in node_ids, f"Cible inconnue : {e.target!r}"

    def test_topo_sort_covers_all_nodes(self, G):
        topo = G.topological_sort()
        assert len(topo) == G.node_count

    def test_predecessor_successor_symmetry(self, G):
        for e in G.edges():
            preds = [p.source for p in G.predecessors(e.target)]
            assert e.source in preds

    def test_summary_contains_key_modules(self, G):
        s = G.summary()
        for mod in ["semgrep", "bearer", "codeql", "neo4j", "tmdd", "opa"]:
            assert mod in s


# ══════════════════════════════════════════════════════════════════════════════
# 2. MÉTADONNÉES DES NŒUDS
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeMeta:

    def test_all_nodes_have_id(self, G):
        for n in G.nodes():
            assert n.meta.id

    def test_all_nodes_have_phase(self, G):
        missing = [n.meta.id for n in G.nodes() if not n.meta.phase]
        assert not missing, f"Nœuds sans phase : {missing[:5]}"

    def test_all_nodes_have_module(self, G):
        missing = [n.meta.id for n in G.nodes() if not n.meta.module]
        assert not missing

    def test_virtual_nodes_flagged(self, G):
        for vid in ["LEON", "CODEBASE", "CODE_GENERATED", "REPORT", "PRODUCTION"]:
            assert G.node(vid).meta.virtual is True

    def test_real_nodes_not_virtual(self, G):
        real = [n for n in G.nodes() if not n.meta.virtual]
        assert all(not n.meta.virtual for n in real)

    def test_node_io_fields_present_for_real_nodes(self, G):
        empty_io = [
            n.meta.id for n in G.nodes()
            if not n.meta.io_in and not n.meta.io_out and not n.meta.virtual
        ]
        assert len(empty_io) == 0, f"Nœuds réels sans io : {empty_io[:5]}"

    def test_node_repr_format(self, G):
        n = G.node("LEON")
        r = repr(n)
        assert "LEON" in r
        assert "live" in r or "stub" in r

    def test_node_is_live_property(self, G):
        """Tous les nœuds enregistrés ont is_live bool."""
        for n in G.nodes():
            assert isinstance(n.is_live, bool)

    def test_list_nodes_by_module(self, G):
        semgrep_nodes = G.list_nodes(module="semgrep")
        assert len(semgrep_nodes) > 0
        for nid in semgrep_nodes:
            assert G.node(nid).meta.module == "semgrep"

    def test_list_nodes_by_phase(self, G):
        audit_nodes = G.list_nodes(phase="audit")
        assert len(audit_nodes) > 0
        for nid in audit_nodes:
            assert G.node(nid).meta.phase == "audit"


# ══════════════════════════════════════════════════════════════════════════════
# 3. TYPES DE NŒUD (Node, Edge, NodeResult) — tests unitaires isolés
# ══════════════════════════════════════════════════════════════════════════════

class TestGraphPrimitives:

    def test_node_result_bool_true(self):
        r = NodeResult(node_id="x", success=True, data={"k": 1})
        assert bool(r) is True

    def test_node_result_bool_false(self):
        r = NodeResult(node_id="x", success=False, error="oops")
        assert bool(r) is False

    def test_node_result_raise_if_failed_ok(self):
        r = NodeResult(node_id="x", success=True)
        assert r.raise_if_failed() is r  # retourne self

    def test_node_result_raise_if_failed_raises(self):
        r = NodeResult(node_id="x", success=False, error="boom")
        with pytest.raises(RuntimeError, match="boom"):
            r.raise_if_failed()

    def test_edge_repr(self):
        e = Edge("A", "B", "label", EdgeType.DATA_FLOW)
        assert "A" in repr(e)
        assert "B" in repr(e)
        assert "data_flow" in repr(e)

    def test_edge_apply_no_transform(self):
        e = Edge("A", "B", "label", EdgeType.DATA_FLOW)
        payload = {"x": 42}
        assert e.apply(payload) is payload  # identité

    def test_edge_apply_with_transform(self):
        e = Edge("A", "B", "label", EdgeType.TRANSFORM,
                 transform=lambda d: {k: v * 2 for k, v in d.items()})
        result = e.apply({"x": 5})
        assert result == {"x": 10}

    def test_minimal_graph_node_count(self):
        g = make_minimal_graph()
        assert g.node_count == 3

    def test_minimal_graph_edge_count(self):
        g = make_minimal_graph()
        assert g.edge_count == 2

    def test_minimal_graph_reachability(self):
        g = make_minimal_graph()
        assert "C" in g.reachable_forward("A")

    def test_minimal_graph_backward(self):
        g = make_minimal_graph()
        assert "A" in g.reachable_backward("C")

    def test_connect_unknown_source_raises(self):
        g = make_minimal_graph()
        with pytest.raises(KeyError, match="Unknown source"):
            g.connect(Edge("X", "A", "bad", EdgeType.DATA_FLOW))

    def test_connect_unknown_target_raises(self):
        g = make_minimal_graph()
        with pytest.raises(KeyError, match="Unknown target"):
            g.connect(Edge("A", "X", "bad", EdgeType.DATA_FLOW))

    def test_node_unknown_raises_keyerror(self, G):
        with pytest.raises(KeyError):
            G.node("this.node.does.not.exist.at.all")

    def test_replace_handler(self):
        g = make_minimal_graph()
        n = g.node("A")
        assert not n.is_live
        n.replace_handler(lambda ctx: {"ok": True})
        assert n.is_live
        result = n({"x": 1})
        assert result.success
        assert result.data == {"ok": True}

    def test_stub_returns_stub_marker(self):
        g = make_minimal_graph()
        n = g.node("A")
        result = n({"inp": "val"})
        assert result.success
        assert result.data.get("_stub") is True

    def test_handler_exception_captured(self):
        g = make_minimal_graph()
        n = g.node("A")
        n.replace_handler(lambda ctx: 1 / 0)
        result = n({})
        assert not result.success
        assert "division" in (result.error or "").lower() or result.error


# ══════════════════════════════════════════════════════════════════════════════
# 4. EXÉCUTION EN STUB (aucun outil externe requis)
# ══════════════════════════════════════════════════════════════════════════════

class TestStubExecution:

    def test_run_node_returns_node_result(self, orch):
        r = orch.run_node("LEON", {"text": "hello"})
        assert isinstance(r, NodeResult)

    def test_all_virtual_nodes_run_without_error(self, orch):
        for vid in ["LEON", "CODEBASE", "CODE_GENERATED", "REPORT", "PRODUCTION"]:
            r = orch.run_node(vid, {"text": "test", "code_path": "."})
            assert isinstance(r, NodeResult)

    def test_pipeline_returns_pipeline_result(self, orch):
        ids = ["CODEBASE", "REPORT"]
        pr = orch.run_pipeline(ids, {})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) == 2

    def test_pipeline_merges_context(self):
        """La sortie dict d'un nœud doit être fusionnée dans le contexte suivant."""
        g = make_minimal_graph()
        g.node("A").replace_handler(lambda ctx: {"merged_key": "merged_value_xyz"})
        orch_local = Orchestrator(g)
        pr = orch_local.run_pipeline(["A", "B"], {})
        assert pr.context.get("merged_key") == "merged_value_xyz"

    def test_pipeline_step_timing(self, orch):
        pr = orch.run_pipeline(["REPORT"], {})
        for step in pr.steps:
            assert step.duration_ms >= 0

    def test_pipeline_total_time(self, orch):
        pr = orch.run_pipeline(["LEON", "REPORT"], {})
        assert pr.total_ms >= 0

    def test_fail_fast_stops_on_first_error(self):
        """
        Déterministe : utilise un graphe isolé avec un handler qui échoue
        volontairement, plutôt que de dépendre d'un binaire absent du PATH
        (qui pourrait être installé selon l'environnement CI).
        """
        g = make_minimal_graph()
        g.node("A").replace_handler(lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        fast_orch = Orchestrator(g, fail_fast=True)

        pr = fast_orch.run_pipeline(["A", "B", "C"], {})

        executed = {s.node_id for s in pr.steps}
        assert executed == {"A"}, f"fail_fast aurait dû arrêter après A, a exécuté {executed}"
        assert not pr.success

    def test_fail_fast_false_continues_after_error(self):
        """Contre-épreuve : fail_fast=False doit exécuter tous les nœuds malgré l'échec de A."""
        g = make_minimal_graph()
        g.node("A").replace_handler(lambda ctx: (_ for _ in ()).throw(RuntimeError("boom")))
        slow_orch = Orchestrator(g, fail_fast=False)

        pr = slow_orch.run_pipeline(["A", "B", "C"], {})

        executed = {s.node_id for s in pr.steps}
        assert executed == {"A", "B", "C"}
        assert not pr.success
        assert ("A", "boom") in [(n, e) for n, e in pr.errors]

    def test_on_step_done_callback(self, G):
        """Le hook on_step_done doit être appelé après chaque étape."""
        recorded = []
        cb_orch = Orchestrator(G, on_step_done=lambda rec: recorded.append(rec.node_id))

        cb_orch.run_pipeline(["LEON", "REPORT"], {})
        assert "LEON" in recorded
        assert "REPORT" in recorded

    def test_dry_run_node_count(self, orch):
        report = orch.dry_run()
        assert len(report.nodes) == orch.G.node_count
        assert report.live_count + report.stub_count == orch.G.node_count

    def test_dry_run_phase_filter(self, orch):
        report = orch.dry_run(orch.G.list_nodes(phase="audit"))
        phases = {n.phase for n in report.nodes}
        assert phases == {"audit"}

    def test_dry_run_str_contains_modules(self, orch):
        s = str(orch.dry_run())
        assert "semgrep" in s
        assert "bearer" in s

    def test_run_phase_audit_runs_nodes(self, orch):
        pr = orch.run_phase("audit", {"target_path": ".", "code_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) > 0

    def test_run_phase_unknown_raises(self, orch):
        with pytest.raises(ValueError):
            orch.run_phase("phase_qui_nexiste_pas_xzq")

    def test_pipeline_summary_format(self, orch):
        pr = orch.run_pipeline(["REPORT", "PRODUCTION"], {})
        s = pr.summary()
        assert "steps" in s or "Pipeline" in s


# ══════════════════════════════════════════════════════════════════════════════
# 5. TOPOLOGIE ET CHEMINS
# ══════════════════════════════════════════════════════════════════════════════

class TestTopology:

    def test_shortest_path_leon_to_production(self, G):
        path = G.shortest_path("LEON", "PRODUCTION")
        assert path is not None
        assert path[0] == "LEON"
        assert path[-1] == "PRODUCTION"
        assert len(path) >= 3

    def test_find_multiple_paths(self, G):
        paths = G.find_paths("CODEBASE", "neo4j.create", max_paths=3)
        assert len(paths) >= 1

    def test_backward_reachability_from_production(self, G):
        back = G.reachable_backward("PRODUCTION")
        assert "tmdd.generate_agent_prompt" in back
        assert "LEON" in back

    def test_neighborhood_neo4j(self, G):
        nb = G.neighborhood("neo4j.create")
        assert "neo4j.match_return" in nb
        assert "semgrep.semgrep_scan" in nb

    def test_topo_sort_respects_order(self, G):
        ids = ["LEON", "q2d.generate", "q2d.fix_format"]
        topo = G.topological_sort(ids)
        assert topo.index("LEON") < topo.index("q2d.generate")

    def test_entry_points_have_no_predecessors(self, G):
        for eid in G.entry_nodes():
            assert not G.predecessors(eid)

    def test_exit_points_have_no_successors(self, G):
        for eid in G.exit_nodes():
            assert not G.successors(eid)

    def test_find_paths_max_depth_respected(self, G):
        paths = G.find_paths("LEON", "PRODUCTION", max_paths=5, max_depth=4)
        for path in paths:
            assert len(path) <= 5  # max_depth=4 → max 5 nodes

    def test_shortest_path_unreachable_returns_none(self, G):
        """PRODUCTION → LEON est impossible (graphe orienté)."""
        path = G.shortest_path("PRODUCTION", "LEON")
        assert path is None

    def test_topo_sort_covers_subgraph(self, G):
        ids = G.list_nodes(phase="audit")
        topo = G.topological_sort(ids)
        assert set(topo) == set(ids)

    def test_minimal_graph_topo(self):
        g = make_minimal_graph()
        topo = g.topological_sort()
        assert topo.index("A") < topo.index("B") < topo.index("C")


# ══════════════════════════════════════════════════════════════════════════════
# 6. TRACE (source → cible)
# ══════════════════════════════════════════════════════════════════════════════

class TestTrace:

    def test_trace_found(self, orch):
        t = orch.trace("LEON", "q2d.generate")
        assert t.found
        assert "LEON" in t.path
        assert "q2d.generate" in t.path

    def test_trace_not_found(self, orch):
        t = orch.trace("PRODUCTION", "LEON")
        assert not t.found

    def test_trace_summary_str_valid(self, orch):
        t = orch.trace("CODEBASE", "semgrep.semgrep_scan")
        s = t.summary()
        assert isinstance(s, str)
        assert len(s) > 0

    def test_trace_not_found_summary(self, orch):
        t = orch.trace("PRODUCTION", "LEON")
        s = t.summary()
        assert "No path" in s or "pas" in s.lower() or "PRODUCTION" in s

    def test_trace_executes_path_nodes(self, orch):
        t = orch.trace("LEON", "q2d.generate")
        assert t.found
        executed = {s.node_id for s in t.steps}
        for node_id in t.path:
            assert node_id in executed


# ══════════════════════════════════════════════════════════════════════════════
# 7. INJECTION DE HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class TestInjection:

    def test_inject_replaces_stub(self, orch, G):
        sentinel = {"injected": True, "value": 42}
        orch.inject("REPORT", lambda ctx: sentinel)
        try:
            r = orch.run_node("REPORT", {})
            assert r.success
            assert r.data == sentinel
        finally:
            G.node("REPORT").replace_handler(None)

    def test_inject_unknown_node_raises(self, orch):
        with pytest.raises(KeyError):
            orch.inject("noeud.fantome", lambda ctx: {})

    def test_inject_context_flows_to_injected_node(self, orch, G):
        received = {}

        def capture(ctx):
            received.update(ctx)
            return {}

        orch.inject("PRODUCTION", capture)
        try:
            orch.run_pipeline(["PRODUCTION"], {"key": "captured_value"})
            assert received.get("key") == "captured_value"
        finally:
            G.node("PRODUCTION").replace_handler(None)


# ══════════════════════════════════════════════════════════════════════════════
# 8. PIPELINES PRESET (stub-safe — sans nœuds inexistants)
# ══════════════════════════════════════════════════════════════════════════════

class TestPresets:

    def test_audit_only_pipeline(self, orch):
        pr = orch.audit_only_pipeline(".", {"target_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) > 0

    def test_threat_model_pipeline(self, orch):
        """
        Exerce le VRAI preset (corrigé par EXTRA_DEFS dans registry.py).
        Voir TestRegressions pour le test ciblé sur le bug lui-même.
        """
        pr = orch.threat_model_pipeline({"elements": [], "relationships": []})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) > 0
        executed = {s.node_id for s in pr.steps}
        assert "codegen.unified_system" in executed
        assert "CODE_GENERATED" in executed

    def test_codegen_pipeline_with_prompt_file(self, orch):
        pr = orch.codegen_pipeline(prompt_file="agent_prompt.txt", feature_name="demo")
        assert isinstance(pr, PipelineResult)
        executed = {s.node_id for s in pr.steps}
        assert "codegen.unified_system" in executed

    def test_codegen_pipeline_without_prompt_file_runs_tmdd_first(self, orch):
        """prompt_file='' doit déclencher le chemin TMDD complet avant codegen."""
        pr = orch.codegen_pipeline(prompt_file="", feature_name="demo")
        executed = [s.node_id for s in pr.steps]
        assert "tmdd.tmdd_init" in executed
        assert executed.index("tmdd.tmdd_init") < executed.index("codegen.unified_system")

    def test_network_validation_pipeline(self, orch):
        pr = orch.network_validation_pipeline("topology.yml", "policy.rego")
        assert isinstance(pr, PipelineResult)

    def test_iter_phase_pipelines_order(self, orch):
        phases_run = []
        for phase, pr in orch.iter_phase_pipelines():
            assert isinstance(pr, PipelineResult)
            phases_run.append(phase)
        assert len(phases_run) > 0
        EXPECTED = ["elicit", "arch", "net", "policy", "threat",
                    "graph", "codegen", "audit", "report", "deploy"]
        for a, b in zip(phases_run, EXPECTED):
            assert a == b, f"Ordre inattendu : {a!r} ≠ {b!r}"

    def test_run_from_codebase(self, orch):
        pr = orch.run_from("CODEBASE", {"code_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) > 0

    def test_run_from_with_edge_filter_data_flow(self, orch):
        """edge_filter restreint à DATA_FLOW uniquement."""
        pr = orch.run_from(
            "CODEBASE",
            ctx={"code_path": "."},
            edge_filter=lambda e: e.type == EdgeType.DATA_FLOW,
        )
        assert isinstance(pr, PipelineResult)


# ══════════════════════════════════════════════════════════════════════════════
# 9. EXÉCUTION PARALLÈLE
# ══════════════════════════════════════════════════════════════════════════════

class TestParallel:

    def test_parallel_independent_nodes(self, orch):
        ids = [
            "bearer.bearer_scan",
            "codeql.codeql_pack_download_install",
            "semgrep.get_semgrep_rule_schema",
        ]
        pr = orch.run_parallel(ids, {"target_path": ".", "code_path": "."})
        assert isinstance(pr, PipelineResult)
        assert len(pr.steps) == 3

    def test_parallel_all_steps_present(self, orch):
        ids = ["LEON", "CODEBASE"]
        pr = orch.run_parallel(ids, {"text": "test"})
        executed = {s.node_id for s in pr.steps}
        assert executed == set(ids)

    def test_parallel_same_context_distributed(self, orch):
        """Chaque nœud reçoit le même contexte initial (copie)."""
        received_keys = []

        def capture(ctx):
            received_keys.append(sorted(ctx.keys()))
            return {}

        G = orch.G
        G.node("LEON").replace_handler(capture)
        G.node("CODEBASE").replace_handler(capture)

        try:
            orch.run_parallel(["LEON", "CODEBASE"], {"shared": "value"})
            assert all("shared" in keys for keys in received_keys)
        finally:
            G.node("LEON").replace_handler(None)
            G.node("CODEBASE").replace_handler(None)

    def test_parallel_exception_in_worker_handled(self, G):
        """Une exception dans un worker ne doit pas planter tout le run."""
        orch = Orchestrator(G)
        G.node("REPORT").replace_handler(lambda ctx: 1 / 0)

        try:
            pr = orch.run_parallel(["REPORT", "PRODUCTION"], {})
            assert isinstance(pr, PipelineResult)
            report_step = next(s for s in pr.steps if s.node_id == "REPORT")
            assert not report_step.success
        finally:
            G.node("REPORT").replace_handler(None)


# ══════════════════════════════════════════════════════════════════════════════
# 10. SÉMANTIQUE DES ARÊTES
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
        store_targets = {e.target for e in G.edges(etype=EdgeType.STORE)}
        assert "neo4j.create" in store_targets

    def test_analyze_edges_from_codeql(self, G):
        analyze_targets = {
            e.target for e in G.successors("codeql.codeql_database_analyze")
            if e.type == EdgeType.ANALYZE
        }
        assert len(analyze_targets) >= 1

    def test_indirect_edges_exist(self, G):
        indirect = list(G.edges(etype=EdgeType.INDIRECT))
        assert len(indirect) >= 1

    def test_report_edges_reach_report_node(self, G):
        report_tgts = {e.target for e in G.edges(etype=EdgeType.REPORT)}
        assert "REPORT" in report_tgts

    def test_validate_edges_exist(self, G):
        validate = list(G.edges(etype=EdgeType.VALIDATE))
        assert len(validate) >= 1

    def test_query_edges_exist(self, G):
        query = list(G.edges(etype=EdgeType.QUERY))
        assert len(query) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# 11. EXCEPTIONS (nexus_compose.exceptions)
# ══════════════════════════════════════════════════════════════════════════════

class TestExceptions:

    def test_node_unavailable_error_inherits_nexus(self):
        err = NodeUnavailableError("semgrep.scan", "semgrep")
        assert isinstance(err, NexusNodeError)

    def test_node_unavailable_error_str(self):
        err = NodeUnavailableError("semgrep.scan", "semgrep")
        s = str(err)
        assert "semgrep" in s.lower()

    def test_node_unavailable_auto_resolves_install_hint(self):
        """Sans install explicite, l'exception doit résoudre via INSTALL_HINTS."""
        err = NodeUnavailableError("semgrep.semgrep_scan", "semgrep")
        assert "pip install semgrep" in err.install
        assert err.doc_url.startswith("https://semgrep.dev")
        assert err.category == "missing_binary"

    def test_node_unavailable_to_dict(self):
        err = NodeUnavailableError("bearer.bearer_scan", "bearer")
        d = err.to_dict()
        assert d["_unavailable"] is True
        assert d["node_id"] == "bearer.bearer_scan"
        assert d["tool"] == "bearer"

    def test_node_execution_error(self):
        err = NodeExecutionError("n5", "boom", exit_code=1)
        assert isinstance(err, NexusNodeError)
        assert err.exit_code == 1
        assert err.error == "boom"

    def test_node_execution_error_default_exit_code(self):
        err = NodeExecutionError("n5", "boom")
        assert err.exit_code == -1

    def test_node_execution_error_to_dict(self):
        err = NodeExecutionError("n5", "boom", exit_code=2)
        d = err.to_dict()
        assert d["_execution_error"] is True
        assert d["exit_code"] == 2

    def test_external_process_error(self):
        err = NodeExternalProcessError("likec4.likec4_serve", "likec4 start <ws>")
        assert isinstance(err, NexusNodeError)
        assert err.command == "likec4 start <ws>"

    def test_external_process_error_to_dict(self):
        err = NodeExternalProcessError("opa.opa_run_server", "opa run --server")
        d = err.to_dict()
        assert d["_external_process"] is True
        assert d["command"] == "opa run --server"

    def test_frontend_only_error(self):
        err = NodeFrontendOnlyError("td.stride_js", "stride.js")
        assert isinstance(err, NexusNodeError)
        assert err.frontend_source == "stride.js"

    def test_frontend_only_error_to_dict(self):
        err = NodeFrontendOnlyError("td.cia_js", "cia.js")
        d = err.to_dict()
        assert d["_frontend_only"] is True

    def test_saas_credentials_error(self):
        err = NodeSaasCredentialsError("semgrep.semgrep_login", "Semgrep Cloud", ["SEMGREP_APP_TOKEN"])
        assert isinstance(err, NexusNodeError)
        assert err.env_vars == ["SEMGREP_APP_TOKEN"]

    def test_saas_credentials_error_to_dict(self):
        err = NodeSaasCredentialsError("likec4.likec4_sync_leanix", "LeanIX", ["LEANIX_API_TOKEN"])
        d = err.to_dict()
        assert d["_saas_required"] is True
        assert d["service"] == "LeanIX"

    def test_all_exception_types_raised_and_caught(self):
        pairs = [
            (NodeUnavailableError, ("n1", "tool")),
            (NodeExecutionError, ("n1b", "err")),
            (NodeExternalProcessError, ("n2", "cmd")),
            (NodeFrontendOnlyError, ("n3", "src")),
            (NodeSaasCredentialsError, ("n4", "svc", ["TOKEN"])),
        ]
        for ExcType, args in pairs:
            with pytest.raises(NexusNodeError):
                raise ExcType(*args)

    def test_unknown_tool_falls_back_to_generic_message(self):
        """Un outil non répertorié dans INSTALL_HINTS doit quand même produire un message utile."""
        err = NodeUnavailableError("foo.bar", "totally_unknown_tool_xyz")
        assert "totally_unknown_tool_xyz" in err.install


# ══════════════════════════════════════════════════════════════════════════════
# 12. NODE AVAILABILITY CHECKER
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeAvailability:

    @pytest.fixture
    def checker(self):
        """Instance fraîche à chaque test (le cache interne ne doit pas fuiter)."""
        return NodeAvailabilityChecker()

    def test_checker_instantiates(self, checker):
        assert checker is not None
        assert checker._cache == {}

    def test_full_report_returns_expected_buckets(self, checker):
        report = checker.full_report()
        assert isinstance(report, dict)
        expected_keys = {"available", "unavailable", "external", "frontend", "saas", "manual"}
        assert set(report.keys()) == expected_keys

    def test_full_report_values_are_toolstatus_lists(self, checker):
        report = checker.full_report()
        for bucket_name, items in report.items():
            assert isinstance(items, list), f"{bucket_name!r} doit être une liste"
            for ts in items:
                assert isinstance(ts, ToolStatus)

    def test_full_report_external_bucket_contains_known_entries(self, checker):
        """opa-server / likec4-server / threat-dragon-server sont toujours 'external'."""
        report = checker.full_report()
        names = {ts.name for ts in report["external"]}
        assert "opa-server" in names
        assert "likec4-server" in names

    def test_full_report_frontend_bucket_contains_threat_dragon(self, checker):
        report = checker.full_report()
        names = {ts.name for ts in report["frontend"]}
        assert "threat-dragon-frontend" in names

    def test_full_report_saas_bucket_contains_semgrep_cloud(self, checker):
        report = checker.full_report()
        names = {ts.name for ts in report["saas"]}
        assert "semgrep-cloud" in names

    def test_check_node_unknown_node_is_available(self, checker):
        """Un node_id non cartographié (ex: nœud virtuel) est considéré disponible."""
        st = checker.check_node("LEON")
        assert st.available is True
        assert st.category == "virtual"

    def test_check_node_known_node_uses_tool_registry(self, checker):
        st = checker.check_node("semgrep.semgrep_scan")
        assert st.name == "semgrep"

    def test_check_tool_caches_result(self, checker):
        st1 = checker.check_tool("semgrep")
        st2 = checker.check_tool("semgrep")
        assert st1 is st2  # même objet → caché

    def test_execution_plan_default_returns_plan(self, checker):
        plan = checker.execution_plan()
        assert isinstance(plan, ExecutionPlan)

    def test_execution_plan_classifies_every_requested_node_exactly_once(self, checker, G):
        """Invariant : chaque node_id passé doit atterrir dans exactement un seau."""
        ids = G.list_nodes(module="semgrep")
        plan = checker.execution_plan(ids)
        total_classified = (
            len(plan.runnable) + len(plan.unavailable) + len(plan.external)
            + len(plan.frontend_only) + len(plan.saas_required)
        )
        assert total_classified == len(ids)

    def test_execution_plan_total_blocked_is_consistent(self, checker, G):
        ids = G.list_nodes(module="bearer")
        plan = checker.execution_plan(ids)
        assert plan.total_blocked == (
            len(plan.unavailable) + len(plan.external)
            + len(plan.frontend_only) + len(plan.saas_required)
        )

    def test_spoken_summary_is_nonempty_string(self, checker, G):
        plan = checker.execution_plan(G.list_nodes(module="codeql"))
        s = plan.spoken_summary()
        assert isinstance(s, str)
        assert len(s) > 0
        assert s.endswith(".")

    def test_execution_plan_phase_map_skipped_when_forced_unavailable(self, monkeypatch):
        """Avec shutil.which forcé à None, une phase 100% binaire doit être 'skipped'."""
        monkeypatch.setattr(node_availability_module.shutil, "which", lambda _: None)
        checker = NodeAvailabilityChecker()
        plan = checker.execution_plan(
            node_ids=["semgrep.semgrep_scan"],
            phase_map={"audit": ["semgrep.semgrep_scan"]},
        )
        assert "audit" in plan.skipped_phases
        assert "semgrep.semgrep_scan" not in plan.runnable

    def test_execution_plan_phase_map_partial_when_mixed(self, monkeypatch):
        """Phase mêlant 1 nœud bloqué + 1 nœud toujours dispo → 'partial', pas 'skipped'."""
        monkeypatch.setattr(node_availability_module.shutil, "which", lambda _: None)
        checker = NodeAvailabilityChecker()
        plan = checker.execution_plan(
            node_ids=["semgrep.semgrep_scan", "LEON"],
            phase_map={"mixed": ["semgrep.semgrep_scan", "LEON"]},
        )
        assert "mixed" in plan.partial_phases
        assert "mixed" not in plan.skipped_phases

    def test_raise_if_unavailable_raises_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr(node_availability_module.shutil, "which", lambda _: None)
        checker = NodeAvailabilityChecker()
        with pytest.raises(NodeUnavailableError):
            checker.raise_if_unavailable("semgrep.semgrep_scan")

    def test_raise_if_unavailable_silent_when_available(self, monkeypatch):
        monkeypatch.setattr(node_availability_module.shutil, "which", lambda b: f"/usr/bin/{b}")
        checker = NodeAvailabilityChecker()
        # Ne doit lever aucune exception
        checker.raise_if_unavailable("semgrep.semgrep_scan")

    def test_raise_if_unavailable_external_category(self, checker):
        """opa.opa_run_server est toujours 'external', peu importe l'environnement."""
        with pytest.raises(NodeExternalProcessError):
            checker.raise_if_unavailable("opa.opa_run_server")

    def test_raise_if_unavailable_frontend_category(self, checker):
        with pytest.raises(NodeFrontendOnlyError):
            checker.raise_if_unavailable("td.stride_js")

    def test_raise_if_unavailable_saas_category(self, checker):
        with pytest.raises(NodeSaasCredentialsError):
            checker.raise_if_unavailable("semgrep.semgrep_login")

    def test_raise_if_unavailable_unknown_node_is_noop(self, checker):
        """Nœud non cartographié → considéré disponible → aucune levée."""
        checker.raise_if_unavailable("PRODUCTION")


# ══════════════════════════════════════════════════════════════════════════════
# 13. RÉGRESSIONS — bugs concrets trouvés dans le dépôt et corrigés
# ══════════════════════════════════════════════════════════════════════════════

class TestRegressions:
    """
    Chaque test ici correspond à un bug réel constaté dans le code source
    (pas une supposition de test) et garantit qu'il ne réapparaît pas.
    """

    def test_codegen_unified_system_node_is_registered(self, G):
        """
        BUG (corrigé) : drivers.py expose un handler live pour
        'codegen.unified_system' (CODEGEN_HANDLERS["unified_system"]) et
        orchestrator.py le référence dans deux presets, mais aucun Node
        n'était enregistré dans le graphe — ni dans nodes.json ni via
        VIRTUAL_DEFS.

        FIX (v2) : codegen.unified_system est maintenant dans nodes.json
        avec module="codegen", function="unified_system". Le handler drivers.py
        est résolu via ALL_HANDLERS["codegen.unified_system"]. Plus besoin
        d'EXTRA_DEFS dans registry.py.
        """
        n = G.node("codegen.unified_system")  # ne doit pas lever KeyError
        assert n is not None
        assert n.is_live, "codegen.unified_system doit avoir un handler live depuis drivers.CODEGEN_HANDLERS"
        assert n.meta.virtual is False
        assert n.meta.module == "codegen"

    def test_codegen_unified_system_is_wired_into_graph(self, G):
        """Le nœud doit être atteignable depuis LEON et alimenter CODE_GENERATED."""
        assert "codegen.unified_system" in G.reachable_forward("LEON")
        assert "codegen.unified_system" in G.reachable_forward("tmdd.generate_agent_prompt")
        successors = {e.target for e in G.successors("codegen.unified_system")}
        assert "CODE_GENERATED" in successors

    def test_codegen_unified_system_predecessor_is_tmdd(self, G):
        predecessors = {e.source for e in G.predecessors("codegen.unified_system")}
        assert "tmdd.generate_agent_prompt" in predecessors

    def test_codegen_unified_system_inject_edge_type(self, G):
        """L'arête tmdd → codegen doit être de type INJECT (contrainte → agent),
        cohérent avec la sémantique des autres arêtes sortantes de TMDD."""
        edge = next(
            e for e in G.successors("tmdd.generate_agent_prompt")
            if e.target == "codegen.unified_system"
        )
        assert edge.type == EdgeType.INJECT

    def test_threat_model_pipeline_does_not_raise_keyerror(self, orch):
        """Régression directe : avant le correctif, cet appel levait
        KeyError: 'codegen.unified_system' à 100 % du temps."""
        pr = orch.threat_model_pipeline({"elements": [], "relationships": []})
        assert isinstance(pr, PipelineResult)

    def test_codegen_pipeline_does_not_raise_keyerror(self, orch):
        """Même régression, second point d'entrée affecté."""
        pr = orch.codegen_pipeline(prompt_file="agent_prompt.txt", feature_name="x")
        assert isinstance(pr, PipelineResult)

    def test_ci_test_file_path_matches_repository_layout(self):
        """
        BUG (avant correctif .github/workflows/ci.yml) : le job 'test'
        exécutait `pytest test_nexus_compose.py` (racine), mais le fichier
        réel vit sous test/test_nexus_compose.py — pytest échouait
        immédiatement avec 'file or directory not found', et puisque le
        job 'deploy' dépend de 'test' (needs: [build, test, codeql]),
        AUCUN déploiement ne pouvait jamais réussir.

        Ce test vérifie simplement que la disposition attendue par ce
        fichier de test lui-même (test/ à la racine du paquet) existe —
        un garde-fou léger contre une régression de structure de dépôt.
        """
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.isfile(os.path.join(repo_root, "test", "test_nexus_compose.py"))
        assert os.path.isdir(os.path.join(repo_root, "nexus_compose"))
