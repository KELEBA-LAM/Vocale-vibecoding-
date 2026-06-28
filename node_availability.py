"""
nexus_compose_patch.node_availability
──────────────────────────────────────
Vérifie la disponibilité RÉELLE de chaque outil avant exécution.

Usage :
    from nexus_compose_patch.node_availability import NodeAvailabilityChecker

    checker = NodeAvailabilityChecker()
    report  = checker.full_report()
    plan    = checker.execution_plan(graph)   # nœuds filtrés + réorganisés

Remplace la logique de _stub_result() par une vérification explicite
AVANT l'exécution, avec rapport vocal adapté pour Leon.
"""
from __future__ import annotations

import importlib
import shutil
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .exceptions import (
    NodeUnavailableError,
    NodeExternalProcessError,
    NodeFrontendOnlyError,
    NodeSaasCredentialsError,
)


# ── Types ─────────────────────────────────────────────────────────────────────

@dataclass
class ToolStatus:
    name: str
    available: bool
    version: str = ""
    path: str = ""
    reason: str = ""          # si indisponible
    install: str = ""
    category: str = ""        # "binary" | "sdk" | "saas" | "external" | "frontend"
    node_ids: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    """
    Plan d'exécution après filtrage des nœuds indisponibles.

    Attributs
    ---------
    runnable        : nœuds qui peuvent s'exécuter immédiatement
    unavailable     : nœuds dont le binaire/SDK est absent (avec instructions)
    external        : nœuds nécessitant un processus externe long-running
    frontend_only   : nœuds JavaScript côté navigateur
    saas_required   : nœuds nécessitant des credentials SaaS
    skipped_phases  : phases entièrement ignorées (0 nœuds runnable)
    partial_phases  : phases avec des nœuds manquants mais au moins 1 runnable
    """
    runnable:       List[str] = field(default_factory=list)
    unavailable:    List[Dict[str, str]] = field(default_factory=list)
    external:       List[Dict[str, str]] = field(default_factory=list)
    frontend_only:  List[Dict[str, str]] = field(default_factory=list)
    saas_required:  List[Dict[str, str]] = field(default_factory=list)
    skipped_phases: List[str] = field(default_factory=list)
    partial_phases: List[str] = field(default_factory=list)

    @property
    def total_blocked(self) -> int:
        return (len(self.unavailable) + len(self.external)
                + len(self.frontend_only) + len(self.saas_required))

    def spoken_summary(self) -> str:
        """Résumé oral adapté au TTS de Leon."""
        parts = [f"{len(self.runnable)} nœuds prêts à exécuter"]
        if self.unavailable:
            tools = list({d["tool"] for d in self.unavailable})[:4]
            parts.append(
                f"{len(self.unavailable)} nœuds bloqués — outils manquants : "
                + ", ".join(tools)
            )
        if self.external:
            parts.append(
                f"{len(self.external)} nœuds nécessitent un processus externe"
            )
        if self.frontend_only:
            parts.append(
                f"{len(self.frontend_only)} nœuds JavaScript (navigateur uniquement)"
            )
        if self.saas_required:
            parts.append(
                f"{len(self.saas_required)} nœuds nécessitent des credentials SaaS"
            )
        if self.skipped_phases:
            parts.append(
                f"Phases ignorées (0 outil installé) : "
                + ", ".join(self.skipped_phases)
            )
        return ". ".join(parts) + "."


# ── Définition des outils par module ─────────────────────────────────────────

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ── Binaires CLI ─────────────────────────────────────────────────────────
    "semgrep": {
        "binary": "semgrep",
        "install": "pip install semgrep  # ou  brew install semgrep",
        "doc": "https://semgrep.dev/docs/getting-started/",
        "category": "binary",
        "nodes": [
            "semgrep.semgrep_scan", "semgrep.semgrep_ci", "semgrep.semgrep_scan_2",
            "semgrep.semgrep_scan_with_custom_rul", "semgrep.semgrep_scan_sca",
            "semgrep.semgrep_findings", "semgrep.get_abstract_syntax_tree",
            "semgrep.write_custom_semgrep_rule", "semgrep.get_semgrep_rule_schema",
            "semgrep.semgrep_mcp",
        ],
    },
    "bearer": {
        "binary": "bearer",
        "install": "brew install bearer  # ou  curl https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh | sh",
        "doc": "https://docs.bearer.com/reference/installation",
        "category": "binary",
        "nodes": [
            "bearer.bearer_scan", "bearer.rapport_security", "bearer.rapport_privacy",
            "bearer.rapport_dataflow", "bearer.rapport_saas", "bearer.export_sarif",
            "bearer.bearer_init", "bearer.bearer_ignore", "bearer.detecteurs_par_langage_detec",
        ],
    },
    "codeql": {
        "binary": "codeql",
        "install": "gh extensions install github/gh-codeql",
        "doc": "https://docs.github.com/en/code-security/codeql-cli",
        "category": "binary",
        "nodes": [
            "codeql.codeql_database_create", "codeql.codeql_database_analyze",
            "codeql.codeql_query_run", "codeql.codeql_pack_download_install",
            "codeql.suite_security_extended_qls_", "codeql.suite_security_and_quality_q",
            "codeql.suite_code_scanning_qls",
        ],
    },
    "likec4": {
        "binary": "likec4",
        "install": "npm install -g @likec4/cli",
        "doc": "https://likec4.dev/docs/getting-started/",
        "category": "binary",
        "nodes": [
            "likec4.likec4_build", "likec4.likec4_validate", "likec4.likec4_format",
            "likec4.likec4_export_json", "likec4.likec4_export_png_jpg",
            "likec4.likec4_export_drawio", "likec4.likec4_codegen_model",
            "likec4.likec4_codegen_react", "likec4.likec4_codegen_webcomponent",
            "likec4.likec4_preview", "likec4.likec4_list_icons", "likec4.likec4_mcp",
            "likec4.query_graph", "likec4.read_element", "likec4.read_view",
            "likec4.read_deployment", "likec4.read_project_summary",
            "likec4.subgraph_summary", "likec4.find_relationships",
            "likec4.element_diff", "likec4.open_view", "likec4.apply_semantic_layout",
            "likec4.list_projects", "likec4.search_element",
            "likec4.query_incomers_graph", "likec4.query_outgoers_graph",
            "likec4.query_by_tags", "likec4.query_by_metadata",
            "likec4.query_by_tag_pattern", "likec4.batch_read_elements",
        ],
    },
    "containerlab": {
        "binary": "containerlab",
        "install": 'bash -c "$(curl -sL https://get.containerlab.dev)"',
        "doc": "https://containerlab.dev/install/",
        "category": "binary",
        "nodes": [
            "clab.clab_generate", "clab.clab_deploy", "clab.clab_destroy",
            "clab.clab_redeploy", "clab.clab_inspect", "clab.clab_inspect_interfaces",
            "clab.clab_graph", "clab.clab_save", "clab.clab_exec",
            "clab.clab_tools_netem", "clab.clab_tools_vxlan", "clab.clab_tools_cert",
        ],
    },
    "opa": {
        "binary": "opa",
        "install": "brew install opa  # ou  curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static && chmod +x opa && mv opa /usr/local/bin/",
        "doc": "https://www.openpolicyagent.org/docs/latest/#running-opa",
        "category": "binary",
        "nodes": [
            "opa.opa_eval", "opa.opa_check", "opa.opa_test", "opa.opa_fmt",
            "opa.opa_build", "opa.opa_sign", "opa.opa_deps",
            "opa.opa_inspect", "opa.opa_parse", "opa.opa_capabilities", "opa.opa_exec",
        ],
    },
    "structurizr-cli": {
        "binary": "structurizr-cli",
        "install": "brew install structurizr/tap/structurizr-cli",
        "doc": "https://github.com/structurizr/cli",
        "category": "binary",
        "nodes": [
            "struct.workspaceparser", "struct.modelparser", "struct.personparser",
            "struct.relationshipparser", "struct.systemcontextviewparser",
            "struct.deploymentenvironmentparser", "struct.dynamicviewparser",
            "struct.stylesparser", "struct.externe_structurizr_export_c",
        ],
    },
    "dotnet": {
        "binary": "dotnet",
        "install": "https://dotnet.microsoft.com/download (SDK .NET 8+)",
        "doc": "https://learn.microsoft.com/en-us/dotnet/core/install/",
        "category": "binary",
        "nodes": [
            "c4if.executeaacstrategycommand", "c4if.drawdiagramscommand",
            "c4if.queryuseflowscommand", "c4if.querybyinputcommand",
            "c4if.generatedocumentationcommand", "c4if.publishsitecommand",
            "c4if.csvtoyamlaacwriter", "c4if.yamltocsvaacgenerator",
            "c4if.executeviewscommand",
        ],
    },
    "tmdd": {
        "binary": "tmdd",
        "install": "pip install -e tmdd-main/",
        "doc": "https://github.com/xvnpw/tmdd",
        "category": "binary",
        "nodes": [
            "tmdd.tmdd_init", "tmdd.tmdd_feature", "tmdd.tmdd_lint",
            "tmdd.tmdd_compile", "tmdd.generate_threat_model_prompt",
            "tmdd.generate_agent_prompt", "tmdd.generate_diagram", "tmdd.generate_report",
        ],
    },
    # ── SDKs Python ──────────────────────────────────────────────────────────
    "neo4j-python": {
        "sdk": "neo4j",
        "install": "pip install neo4j  +  démarrer Neo4j (docker run neo4j ou neo4j start)",
        "doc": "https://neo4j.com/docs/python-manual/current/",
        "category": "sdk",
        "nodes": [
            "neo4j.create", "neo4j.match_return", "neo4j.match_where_chemin_variable",
            "neo4j.set", "neo4j.db_schema_visualization",
            "neo4j.db_schema_nodetypeproperties", "neo4j.db_labels",
            "neo4j.contraintes_index_create_con", "neo4j.dbms_listconfig",
        ],
    },
    "pybatfish": {
        "sdk": "pybatfish",
        "install": "pip install pybatfish  +  démarrer Batfish (docker run batfish/allinone)",
        "doc": "https://pybatfish.readthedocs.io/",
        "category": "sdk",
        "nodes": [
            "bf.bfq_testfilters", "bf.bfq_routes", "bf.bfq_bgpedges",
            "bf.bfq_undefinedreferences", "bf.bfq_unusedstructures",
            "bf.bfq_initissues", "bf.bfq_ipowners",
            "bf.bfq_aaaauthenticationlogin", "bf.bfq_ipsecsessionstatus",
            "bf.bfq_vxlanedges",
        ],
    },
    "pytm": {
        "sdk": "pytm",
        "install": "pip install pytm  # ou  pip install -e pytm-master/",
        "doc": "https://owasp-pytm.readthedocs.io/",
        "category": "sdk",
        "nodes": [
            "pytm.tm_process", "pytm.tm_resolve", "pytm.tm_check",
            "pytm.tm_dfd", "pytm.tm_seq", "pytm.tm_report", "pytm.json",
            "pytm.list", "pytm.describe", "pytm.stale",
            "pytm.llm_threats", "pytm.ci_pipeline", "pytm.versioning",
        ],
    },
    "q2d": {
        "sdk": "q2d",
        "install": "pip install -e query2diagram-main/",
        "doc": "https://github.com/xvnpw/sec-docs",
        "category": "sdk",
        "nodes": [
            "q2d.generate", "q2d.traverse_project", "q2d.convert_graph",
            "q2d.fix_format", "q2d.openaiengine_generate",
        ],
    },
    # ── Processus externes long-running ──────────────────────────────────────
    "likec4-server": {
        "external_command": "likec4 start <workspace> --port 61000",
        "category": "external",
        "nodes": ["likec4.likec4_serve"],
    },
    "opa-server": {
        "external_command": "opa run --server -b <bundle> --addr 0.0.0.0:8181",
        "category": "external",
        "nodes": ["opa.opa_run_server"],
    },
    "threat-dragon-server": {
        "external_command": "docker run -p 3000:3000 owasp/threat-dragon:latest",
        "category": "external",
        "nodes": [
            "td.threatmodelcontroller_create", "td.threatmodelcontroller_update",
            "td.threatmodelcontroller_model", "td.threatmodelcontroller_delete",
            "td.threatmodelcontroller_repos", "td.editeur_de_diagramme_x6_form",
        ],
    },
    # ── JavaScript côté navigateur uniquement ────────────────────────────────
    "threat-dragon-frontend": {
        "category": "frontend",
        "nodes": [
            "td.stride_js", "td.linddun_js", "td.cia_js",
            "td.plot4ai_js", "td.cornucopia_js",
            "td.context_generator_js_oats", "td.tmbom_js_migration",
        ],
    },
    # ── Credentials SaaS requis ───────────────────────────────────────────────
    "semgrep-cloud": {
        "service": "Semgrep Cloud",
        "env_vars": ["SEMGREP_APP_TOKEN"],
        "category": "saas",
        "nodes": ["semgrep.semgrep_login", "semgrep.semgrep_publish"],
    },
    "leanix": {
        "service": "LeanIX SaaS",
        "env_vars": ["LEANIX_API_TOKEN", "LEANIX_WORKSPACE"],
        "category": "saas",
        "nodes": ["likec4.likec4_sync_leanix"],
    },
    # ── Opérations manuelles (pas de CLI automatisable) ──────────────────────
    "manual-q2d": {
        "category": "manual",
        "reason": "Opération manuelle : migration de format — à exécuter manuellement",
        "nodes": ["q2d.migration", "q2d.find_similar_items"],
    },
}

# Mapping inverse node_id → tool_key
_NODE_TO_TOOL: Dict[str, str] = {}
for _tool_key, _tool_def in TOOL_REGISTRY.items():
    for _nid in _tool_def.get("nodes", []):
        _NODE_TO_TOOL[_nid] = _tool_key


# ── Vérificateur de disponibilité ────────────────────────────────────────────

class NodeAvailabilityChecker:
    """
    Vérifie la disponibilité réelle de chaque outil AVANT exécution.
    Remplace la détection paresseuse (stub au moment de l'exécution).
    """

    def __init__(self) -> None:
        self._cache: Dict[str, ToolStatus] = {}

    # ── Vérification d'un outil ───────────────────────────────────────────────

    def check_tool(self, tool_key: str) -> ToolStatus:
        if tool_key in self._cache:
            return self._cache[tool_key]

        info = TOOL_REGISTRY.get(tool_key, {})
        category = info.get("category", "binary")

        status = ToolStatus(
            name=tool_key,
            available=False,
            category=category,
            node_ids=info.get("nodes", []),
        )

        if category == "binary":
            binary = info.get("binary", tool_key)
            path = shutil.which(binary)
            if path:
                status.available = True
                status.path = path
                # Tentative de récupération de version
                try:
                    import subprocess
                    r = subprocess.run(
                        [path, "--version"], capture_output=True, text=True, timeout=5
                    )
                    status.version = (r.stdout + r.stderr).split("\n")[0].strip()
                except Exception:
                    pass
            else:
                status.reason  = f"Binaire '{binary}' absent du PATH"
                status.install = info.get("install", f"Installer '{binary}'")

        elif category == "sdk":
            sdk = info.get("sdk", "")
            try:
                mod = importlib.import_module(sdk)
                status.available = True
                status.version = getattr(mod, "__version__", "?")
            except ImportError:
                status.reason  = f"Package Python '{sdk}' non installé"
                status.install = info.get("install", f"pip install {sdk}")

        elif category in ("external", "frontend", "saas", "manual"):
            # Ces catégories ne sont JAMAIS "disponibles" inline
            status.available = False
            status.reason = {
                "external": f"Processus externe : {info.get('external_command', '')}",
                "frontend": "Module JavaScript côté navigateur — non exécutable server-side",
                "saas":     f"Credentials SaaS requis : {', '.join(info.get('env_vars', []))}",
                "manual":   info.get("reason", "Opération manuelle"),
            }.get(category, "Indisponible")
            status.install = info.get("install", "")

        self._cache[tool_key] = status
        return status

    def check_node(self, node_id: str) -> ToolStatus:
        """Retourne le statut de l'outil requis par un node_id."""
        tool_key = _NODE_TO_TOOL.get(node_id)
        if not tool_key:
            # Nœud virtuel ou inconnu → supposé disponible
            return ToolStatus(name=node_id, available=True, category="virtual")
        return self.check_tool(tool_key)

    # ── Rapport global ────────────────────────────────────────────────────────

    def full_report(self) -> Dict[str, List[ToolStatus]]:
        """Vérifie tous les outils et retourne un rapport groupé par disponibilité."""
        available, unavailable, external, frontend, saas, manual = [], [], [], [], [], []

        for tool_key in TOOL_REGISTRY:
            st = self.check_tool(tool_key)
            if st.available:
                available.append(st)
            elif st.category == "external":
                external.append(st)
            elif st.category == "frontend":
                frontend.append(st)
            elif st.category == "saas":
                saas.append(st)
            elif st.category == "manual":
                manual.append(st)
            else:
                unavailable.append(st)

        return {
            "available":   available,
            "unavailable": unavailable,
            "external":    external,
            "frontend":    frontend,
            "saas":        saas,
            "manual":      manual,
        }

    # ── Plan d'exécution filtré ───────────────────────────────────────────────

    def execution_plan(
        self,
        node_ids: Optional[List[str]] = None,
        phase_map: Optional[Dict[str, List[str]]] = None,
    ) -> ExecutionPlan:
        """
        Construit un plan d'exécution en filtrant les nœuds indisponibles
        et en signalant clairement chaque problème.

        Paramètres
        ----------
        node_ids  : liste de node_ids à évaluer (tous si None)
        phase_map : {phase_name: [node_ids]} pour détection phases partielles
        """
        if node_ids is None:
            node_ids = list(_NODE_TO_TOOL.keys())

        plan = ExecutionPlan()

        for nid in node_ids:
            st = self.check_node(nid)
            info = TOOL_REGISTRY.get(_NODE_TO_TOOL.get(nid, ""), {})

            if st.available:
                plan.runnable.append(nid)
            elif st.category == "external":
                plan.external.append({
                    "node_id": nid,
                    "command": info.get("external_command", ""),
                    "reason":  st.reason,
                })
            elif st.category == "frontend":
                plan.frontend_only.append({
                    "node_id": nid,
                    "source":  info.get("frontend_source", ""),
                    "reason":  st.reason,
                })
            elif st.category == "saas":
                plan.saas_required.append({
                    "node_id":  nid,
                    "service":  info.get("service", ""),
                    "env_vars": info.get("env_vars", []),
                })
            else:
                plan.unavailable.append({
                    "node_id": nid,
                    "tool":    st.name,
                    "reason":  st.reason,
                    "install": st.install,
                })

        # Analyse par phase
        if phase_map:
            for phase, phase_nodes in phase_map.items():
                runnable_in_phase = [n for n in phase_nodes if n in plan.runnable]
                if not runnable_in_phase:
                    plan.skipped_phases.append(phase)
                elif len(runnable_in_phase) < len(phase_nodes):
                    plan.partial_phases.append(phase)

        return plan

    # ── Levée d'exception explicite ───────────────────────────────────────────

    def raise_if_unavailable(self, node_id: str) -> None:
        """
        Lève l'exception appropriée si le nœud n'est pas disponible.
        À appeler au début de chaque handler en remplacement du try/except stub.

        Usage dans drivers.py :
            checker = NodeAvailabilityChecker()

            def _sg_scan(ctx):
                checker.raise_if_unavailable("semgrep.semgrep_scan")
                # ... exécution normale ...
        """
        st = self.check_node(node_id)
        info = TOOL_REGISTRY.get(_NODE_TO_TOOL.get(node_id, ""), {})

        if st.available:
            return  # Tout va bien

        category = st.category

        if category == "external":
            raise NodeExternalProcessError(
                node_id=node_id,
                command=info.get("external_command", ""),
                reason=st.reason,
            )
        elif category == "frontend":
            raise NodeFrontendOnlyError(
                node_id=node_id,
                frontend_source=info.get("nodes", [node_id])[0],
                reason=st.reason,
            )
        elif category == "saas":
            raise NodeSaasCredentialsError(
                node_id=node_id,
                service=info.get("service", ""),
                env_vars=info.get("env_vars", []),
            )
        else:
            raise NodeUnavailableError(
                node_id=node_id,
                tool=info.get("binary") or info.get("sdk") or st.name,
                reason=st.reason,
                install=st.install,
                category=category,
            )

    # ── Rapport vocal pour Leon ───────────────────────────────────────────────

    def leon_spoken_report(self) -> str:
        """
        Génère un résumé oral adapté au TTS de Leon.
        Ex : "3 outils disponibles. Semgrep manquant — pip install semgrep.
              LikeC4 manquant — npm install -g @likec4/cli."
        """
        report = self.full_report()
        parts = []

        n_avail = len(report["available"])
        n_miss  = len(report["unavailable"])
        parts.append(f"{n_avail} outil{'s' if n_avail > 1 else ''} disponible{'s' if n_avail > 1 else ''}")

        if report["unavailable"]:
            for st in report["unavailable"][:3]:  # max 3 pour ne pas saturer TTS
                parts.append(f"{st.name} manquant — {st.install}")

        if report["external"]:
            cmds = [i.get("external_command", "") for i in report["external"][:2]]
            parts.append(f"Processus externes à lancer manuellement : {', '.join(cmds)}")

        if report["saas"]:
            services = [st.name for st in report["saas"][:2]]
            parts.append(f"Credentials SaaS requis : {', '.join(services)}")

        return ". ".join(parts) + "."
