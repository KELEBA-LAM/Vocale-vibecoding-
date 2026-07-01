"""
nexus_compose.registry
──────────────────────
Builds the canonical, fully-wired ComposabilityGraph.

    build() → ComposabilityGraph   (call once at startup)

All 169 nodes (164 parsed + 5 virtual) and all 218 edges are registered
here.  Each node gets its live handler from drivers.ALL_HANDLERS; nodes
without a handler fall back to Node's built-in stub mode.

Nœuds parsés (164) :
  - 163 nœuds d'outils tiers (q2d, likec4, c4if, struct, clab, opa, bf,
    td, pytm, neo4j, tmdd, semgrep, bearer, codeql)
  - 1  nœud de pont  : codegen.unified_system (crewAI + OpenHands + RL)

Nœuds virtuels (5) : LEON, CODEBASE, CODE_GENERATED, REPORT, PRODUCTION
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Tuple

from .graph import (
    ComposabilityGraph, Edge, EdgeType, Node, NodeMeta
)
from .drivers import ALL_HANDLERS

logger = logging.getLogger(__name__)

# ── node JSON path ─────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent


def _find_nodes_json() -> Path:
    for candidate in [
        _HERE / "nodes.json",
        _HERE.parent / "nodes.json",
        Path("nodes.json"),
    ]:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "nodes.json not found. Run: python nexus_compose/tools/parse_nodes.py"
    )


# ── edge catalogue ─────────────────────────────────────────────────────────────
# (source_id, target_id, label, EdgeType)
_EDGE_TYPE = {k.value: k for k in EdgeType}

RAW_EDGES: list[Tuple[str, str, str, EdgeType]] = [
    # ── VIRTUAL INPUTS ────────────────────────────────────────────────────────
    ("LEON","q2d.generate","commande vocale",EdgeType.DATA_FLOW),
    ("LEON","q2d.openaiengine_generate","requête LLM",EdgeType.DATA_FLOW),
    ("LEON","likec4.likec4_mcp","requête archi vocale",EdgeType.DATA_FLOW),
    ("LEON","semgrep.semgrep_mcp","audit vocal",EdgeType.DATA_FLOW),
    ("CODEBASE","q2d.traverse_project","dépôt existant",EdgeType.DATA_FLOW),
    ("CODEBASE","c4if.executeaacstrategycommand","code C#",EdgeType.DATA_FLOW),
    ("CODEBASE","codeql.codeql_database_create","code source",EdgeType.DATA_FLOW),
    ("CODEBASE","bearer.bearer_init","code source",EdgeType.DATA_FLOW),
    ("CODEBASE","semgrep.semgrep_scan","code source",EdgeType.DATA_FLOW),
    ("CODE_GENERATED","semgrep.semgrep_scan","code généré",EdgeType.DATA_FLOW),
    ("CODE_GENERATED","semgrep.semgrep_ci","code généré",EdgeType.DATA_FLOW),
    ("CODE_GENERATED","bearer.bearer_init","code généré",EdgeType.DATA_FLOW),
    ("CODE_GENERATED","codeql.codeql_database_create","code généré",EdgeType.DATA_FLOW),

    # ── Q2D ──────────────────────────────────────────────────────────────────
    ("q2d.traverse_project","q2d.generate","fichiers source",EdgeType.DATA_FLOW),
    ("q2d.openaiengine_generate","q2d.generate","inférence LLM",EdgeType.DATA_FLOW),
    ("q2d.generate","q2d.fix_format","JSON brut",EdgeType.TRANSFORM),
    ("q2d.fix_format","q2d.convert_graph","JSON valide",EdgeType.TRANSFORM),
    ("q2d.migration","q2d.convert_graph","JSON migré",EdgeType.TRANSFORM),
    ("q2d.find_similar_items","q2d.generate","corpus filtré",EdgeType.VALIDATE),
    ("q2d.convert_graph","likec4.likec4_build","PlantUML → C4 DSL",EdgeType.INDIRECT),
    ("q2d.traverse_project","c4if.executeaacstrategycommand","code existant",EdgeType.DATA_FLOW),

    # ── LIKEC4 ────────────────────────────────────────────────────────────────
    ("likec4.likec4_build","likec4.likec4_format","modèle brut",EdgeType.TRANSFORM),
    ("likec4.likec4_format","likec4.likec4_validate","modèle formaté",EdgeType.VALIDATE),
    ("likec4.likec4_validate","likec4.likec4_export_json","modèle validé",EdgeType.TRANSFORM),
    ("likec4.likec4_validate","likec4.likec4_codegen_model","modèle validé",EdgeType.DATA_FLOW),
    ("likec4.likec4_validate","likec4.likec4_export_png_jpg","modèle validé",EdgeType.TRANSFORM),
    ("likec4.likec4_validate","likec4.likec4_export_drawio","modèle validé",EdgeType.TRANSFORM),
    ("likec4.likec4_validate","likec4.likec4_serve","modèle validé",EdgeType.DATA_FLOW),
    ("likec4.likec4_validate","likec4.likec4_preview","modèle validé",EdgeType.DATA_FLOW),
    ("likec4.likec4_codegen_react","CODE_GENERATED","composant React C4",EdgeType.DATA_FLOW),
    ("likec4.likec4_codegen_webcomponent","CODE_GENERATED","web component C4",EdgeType.DATA_FLOW),
    ("likec4.likec4_mcp","likec4.query_graph","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.read_element","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.find_relationships","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.list_projects","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.read_project_summary","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.query_incomers_graph","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.query_by_tags","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.query_by_metadata","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.search_element","serveur MCP actif",EdgeType.QUERY),
    ("likec4.likec4_mcp","likec4.read_deployment","serveur MCP actif",EdgeType.QUERY),
    ("likec4.query_graph","likec4.subgraph_summary","sous-graphe",EdgeType.QUERY),
    ("likec4.query_graph","likec4.read_view","sous-graphe → vue",EdgeType.QUERY),
    ("likec4.query_graph","likec4.element_diff","diff",EdgeType.QUERY),
    ("likec4.query_by_metadata","likec4.read_element","éléments filtrés par propriété",EdgeType.QUERY),
    ("likec4.query_by_metadata","neo4j.create","métadonnées architecture",EdgeType.STORE),
    ("likec4.find_relationships","likec4.apply_semantic_layout","chemins",EdgeType.DATA_FLOW),
    ("likec4.read_view","likec4.open_view","vue → UI",EdgeType.DATA_FLOW),
    ("likec4.read_view","REPORT","vue C4",EdgeType.REPORT),
    ("likec4.subgraph_summary","neo4j.create","résumé sous-graphe",EdgeType.STORE),
    ("likec4.element_diff","REPORT","diff élément C4",EdgeType.REPORT),
    ("likec4.query_by_tags","likec4.read_element","éléments filtrés",EdgeType.QUERY),
    ("likec4.search_element","likec4.read_element","éléments",EdgeType.QUERY),
    ("likec4.read_deployment","clab.clab_generate","modèle déploiement",EdgeType.DATA_FLOW),
    ("likec4.likec4_export_json","neo4j.create","modèle C4 JSON",EdgeType.STORE),
    ("likec4.likec4_export_json","pytm.tm_process","C4 → pytm (bridge)",EdgeType.INDIRECT),
    ("likec4.likec4_export_json","td.editeur_de_diagramme_x6_form","C4 → DFD (bridge)",EdgeType.INDIRECT),
    ("likec4.likec4_codegen_model","CODE_GENERATED","bindings TypeScript",EdgeType.DATA_FLOW),
    ("likec4.likec4_preview","REPORT","preview C4",EdgeType.REPORT),

    # ── C4INTERFLOW ───────────────────────────────────────────────────────────
    ("c4if.executeaacstrategycommand","c4if.drawdiagramscommand","AaC",EdgeType.TRANSFORM),
    ("c4if.executeaacstrategycommand","c4if.queryuseflowscommand","AaC",EdgeType.QUERY),
    ("c4if.executeaacstrategycommand","c4if.querybyinputcommand","AaC",EdgeType.QUERY),
    ("c4if.csvtoyamlaacwriter","c4if.executeaacstrategycommand","CSV → AaC",EdgeType.TRANSFORM),
    ("c4if.yamltocsvaacgenerator","c4if.executeaacstrategycommand","AaC converti",EdgeType.TRANSFORM),
    ("c4if.generatedocumentationcommand","REPORT","documentation AaC",EdgeType.REPORT),
    ("c4if.publishsitecommand","REPORT","site statique",EdgeType.REPORT),
    ("c4if.queryuseflowscommand","neo4j.create","flux d'usage",EdgeType.STORE),
    ("c4if.queryuseflowscommand","td.editeur_de_diagramme_x6_form","flux → DFD",EdgeType.DATA_FLOW),
    ("c4if.queryuseflowscommand","pytm.tm_process","flux → pytm dataflows",EdgeType.DATA_FLOW),
    ("c4if.drawdiagramscommand","neo4j.create","diagrammes AaC",EdgeType.STORE),
    ("c4if.querybyinputcommand","neo4j.create","structures AaC",EdgeType.STORE),

    # ── STRUCTURIZR DSL ───────────────────────────────────────────────────────
    ("struct.workspaceparser","struct.modelparser","workspace",EdgeType.DATA_FLOW),
    ("struct.modelparser","struct.personparser","bloc model",EdgeType.DATA_FLOW),
    ("struct.modelparser","struct.relationshipparser","bloc model",EdgeType.DATA_FLOW),
    ("struct.modelparser","struct.systemcontextviewparser","bloc views",EdgeType.DATA_FLOW),
    ("struct.modelparser","struct.deploymentenvironmentparser","bloc deployment",EdgeType.DATA_FLOW),
    ("struct.modelparser","struct.dynamicviewparser","bloc dynamic",EdgeType.DATA_FLOW),
    ("struct.modelparser","struct.stylesparser","bloc styles",EdgeType.DATA_FLOW),
    ("struct.stylesparser","struct.externe_structurizr_export_c","styles → export",EdgeType.DATA_FLOW),
    ("struct.externe_structurizr_export_c","neo4j.create","PlantUML/Mermaid",EdgeType.STORE),

    # ── CONTAINERLAB ──────────────────────────────────────────────────────────
    ("clab.clab_generate","clab.clab_deploy","topologie YAML",EdgeType.DATA_FLOW),
    ("clab.clab_tools_cert","clab.clab_deploy","certificats TLS",EdgeType.DATA_FLOW),
    ("clab.clab_deploy","clab.clab_inspect","lab actif",EdgeType.QUERY),
    ("clab.clab_deploy","clab.clab_inspect_interfaces","lab actif",EdgeType.QUERY),
    ("clab.clab_deploy","clab.clab_save","lab actif",EdgeType.DATA_FLOW),
    ("clab.clab_deploy","clab.clab_exec","lab actif",EdgeType.SIMULATE),
    ("clab.clab_deploy","clab.clab_redeploy","lab actif",EdgeType.SIMULATE),
    ("clab.clab_deploy","clab.clab_destroy","lab actif",EdgeType.SIMULATE),
    ("clab.clab_tools_netem","clab.clab_deploy","lien modifié",EdgeType.SIMULATE),
    ("clab.clab_tools_vxlan","bf.bfq_vxlanedges","tunnel VXLAN",EdgeType.VALIDATE),
    ("clab.clab_graph","REPORT","topologie visuelle",EdgeType.REPORT),
    ("clab.clab_save","bf.bfq_testfilters","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_routes","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_undefinedreferences","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_initissues","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_ipowners","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_aaaauthenticationlogin","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_ipsecsessionstatus","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_unusedstructures","startup-configs",EdgeType.DATA_FLOW),
    ("clab.clab_save","bf.bfq_bgpedges","startup-configs",EdgeType.DATA_FLOW),

    # ── BATFISH → OPA ─────────────────────────────────────────────────────────
    ("bf.bfq_testfilters","opa.opa_eval","résultat ACL → JSON",EdgeType.DATA_FLOW),
    ("bf.bfq_routes","opa.opa_eval","routes → JSON",EdgeType.DATA_FLOW),
    ("bf.bfq_undefinedreferences","opa.opa_eval","erreurs config → JSON",EdgeType.DATA_FLOW),
    ("bf.bfq_ipowners","opa.opa_eval","conflits IP → JSON",EdgeType.DATA_FLOW),
    ("bf.bfq_bgpedges","opa.opa_eval","adjacences BGP → JSON",EdgeType.DATA_FLOW),
    ("bf.bfq_unusedstructures","opa.opa_eval","objets inutilisés → JSON",EdgeType.DATA_FLOW),
    ("bf.bfq_aaaauthenticationlogin","opa.opa_eval","conformité AAA",EdgeType.VALIDATE),
    ("bf.bfq_initissues","opa.opa_eval","erreurs init → JSON",EdgeType.VALIDATE),
    ("bf.bfq_vxlanedges","opa.opa_eval","tunnels VXLAN",EdgeType.VALIDATE),
    ("bf.bfq_ipsecsessionstatus","opa.opa_eval","sessions IPsec",EdgeType.VALIDATE),

    # ── OPA ────────────────────────────────────────────────────────────────────
    ("opa.opa_parse","opa.opa_fmt","AST Rego",EdgeType.TRANSFORM),
    ("opa.opa_parse","opa.opa_check","AST Rego",EdgeType.VALIDATE),
    ("opa.opa_check","opa.opa_test","Rego validé",EdgeType.VALIDATE),
    ("opa.opa_check","opa.opa_deps","arbre dep",EdgeType.QUERY),
    ("opa.opa_test","opa.opa_build","tests passés",EdgeType.DATA_FLOW),
    ("opa.opa_build","opa.opa_sign","bundle",EdgeType.DATA_FLOW),
    ("opa.opa_build","opa.opa_inspect","bundle",EdgeType.QUERY),
    ("opa.opa_build","opa.opa_run_server","bundle déployé",EdgeType.DATA_FLOW),
    ("opa.opa_build","opa.opa_exec","bundle + inputs batch",EdgeType.VALIDATE),
    ("opa.opa_run_server","opa.opa_eval","requête HTTP",EdgeType.VALIDATE),
    ("opa.opa_run_server","PRODUCTION","politiques actives",EdgeType.DATA_FLOW),
    ("opa.opa_exec","neo4j.create","résultats batch → graphe",EdgeType.STORE),
    ("opa.opa_exec","REPORT","rapport conformité batch",EdgeType.REPORT),
    ("opa.opa_eval","tmdd.generate_agent_prompt","décision politique",EdgeType.INJECT),
    ("neo4j.match_return","opa.opa_eval","données graphe → Rego",EdgeType.DATA_FLOW),
    ("neo4j.match_return","opa.opa_exec","données graphe batch",EdgeType.DATA_FLOW),

    # ── THREAT DRAGON ─────────────────────────────────────────────────────────
    ("td.threatmodelcontroller_repos","td.threatmodelcontroller_create","repo sélectionné",EdgeType.DATA_FLOW),
    ("td.threatmodelcontroller_create","td.editeur_de_diagramme_x6_form","modèle initialisé",EdgeType.DATA_FLOW),
    ("td.tmbom_js_migration","td.threatmodelcontroller_update","modèle migré",EdgeType.TRANSFORM),
    ("td.threatmodelcontroller_update","td.editeur_de_diagramme_x6_form","modèle mis à jour",EdgeType.DATA_FLOW),
    ("td.threatmodelcontroller_model","td.editeur_de_diagramme_x6_form","modèle existant",EdgeType.DATA_FLOW),
    ("td.editeur_de_diagramme_x6_form","td.stride_js","DFD éléments",EdgeType.DATA_FLOW),
    ("td.editeur_de_diagramme_x6_form","td.linddun_js","DFD éléments",EdgeType.DATA_FLOW),
    ("td.editeur_de_diagramme_x6_form","td.cia_js","DFD éléments",EdgeType.DATA_FLOW),
    ("td.editeur_de_diagramme_x6_form","td.plot4ai_js","DFD éléments",EdgeType.DATA_FLOW),
    ("td.editeur_de_diagramme_x6_form","td.cornucopia_js","DFD éléments",EdgeType.DATA_FLOW),
    ("td.context_generator_js_oats","tmdd.tmdd_feature","scénarios de test",EdgeType.DATA_FLOW),
    ("td.stride_js","neo4j.create","menaces STRIDE",EdgeType.STORE),
    ("td.linddun_js","neo4j.create","menaces LINDDUN",EdgeType.STORE),
    ("td.cia_js","neo4j.create","menaces CIA/DIE",EdgeType.STORE),

    # ── PYTM ──────────────────────────────────────────────────────────────────
    ("pytm.list","pytm.tm_process","catalogue menaces",EdgeType.DATA_FLOW),
    ("pytm.describe","pytm.tm_process","doc menace ciblée",EdgeType.DATA_FLOW),
    ("pytm.versioning","pytm.tm_process","script tm.py versionné",EdgeType.DATA_FLOW),
    ("pytm.tm_process","pytm.tm_resolve","modèle",EdgeType.DATA_FLOW),
    ("pytm.tm_resolve","pytm.tm_check","modèle résolu",EdgeType.VALIDATE),
    ("pytm.tm_resolve","pytm.tm_dfd","modèle résolu",EdgeType.TRANSFORM),
    ("pytm.tm_resolve","pytm.tm_seq","modèle résolu → séquence PlantUML",EdgeType.TRANSFORM),
    ("pytm.tm_resolve","pytm.tm_report","modèle résolu",EdgeType.TRANSFORM),
    ("pytm.tm_resolve","pytm.json","modèle résolu",EdgeType.TRANSFORM),
    ("pytm.tm_resolve","pytm.llm_threats","filtre 8 menaces LLM",EdgeType.TRANSFORM),
    ("pytm.stale","pytm.tm_process","alerte dérive --stale-days N",EdgeType.VALIDATE),
    ("pytm.stale","pytm.ci_pipeline","vérif. dérive CI",EdgeType.VALIDATE),
    ("pytm.json","neo4j.create","menaces JSON",EdgeType.STORE),
    ("pytm.json","pytm.ci_pipeline","findings → pipeline",EdgeType.DATA_FLOW),
    ("pytm.tm_dfd","neo4j.create","DFD → graphe",EdgeType.STORE),
    ("pytm.tm_report","REPORT","rapport menaces HTML/MD",EdgeType.REPORT),
    ("pytm.tm_seq","REPORT","séquence PlantUML",EdgeType.REPORT),
    ("pytm.json","tmdd.tmdd_init","modèle de menaces",EdgeType.DATA_FLOW),
    ("pytm.llm_threats","neo4j.create","menaces LLM → graphe",EdgeType.STORE),
    ("pytm.llm_threats","tmdd.tmdd_feature","contraintes LLM agent",EdgeType.INJECT),
    ("pytm.ci_pipeline","REPORT","rapport CI findings",EdgeType.REPORT),

    # ── NEO4J ─────────────────────────────────────────────────────────────────
    ("neo4j.contraintes_index_create_con","neo4j.create","contrainte",EdgeType.STORE),
    ("neo4j.create","neo4j.match_return","nœuds/relations stockés",EdgeType.QUERY),
    ("neo4j.match_return","neo4j.match_where_chemin_variable","résultats filtrés",EdgeType.QUERY),
    ("neo4j.match_return","neo4j.set","nœud ciblé",EdgeType.STORE),
    ("neo4j.db_schema_visualization","neo4j.match_return","schéma courant",EdgeType.QUERY),
    ("neo4j.db_schema_visualization","neo4j.db_schema_nodetypeproperties","schéma",EdgeType.QUERY),
    ("neo4j.db_schema_visualization","neo4j.db_labels","labels",EdgeType.QUERY),
    ("neo4j.match_return","tmdd.generate_agent_prompt","contexte graphe unifié",EdgeType.INJECT),
    ("neo4j.match_where_chemin_variable","tmdd.generate_agent_prompt","chemins threat→composant",EdgeType.INJECT),

    # ── TMDD ──────────────────────────────────────────────────────────────────
    ("tmdd.tmdd_init","tmdd.tmdd_feature","projet .tmdd/ initialisé",EdgeType.DATA_FLOW),
    ("tmdd.tmdd_feature","tmdd.generate_threat_model_prompt","feature + code",EdgeType.DATA_FLOW),
    ("tmdd.tmdd_feature","tmdd.tmdd_lint","squelette YAML",EdgeType.VALIDATE),
    ("tmdd.generate_threat_model_prompt","tmdd.tmdd_lint","prompt → modèle",EdgeType.DATA_FLOW),
    ("tmdd.tmdd_lint","tmdd.tmdd_compile","modèle validé",EdgeType.TRANSFORM),
    ("tmdd.tmdd_compile","tmdd.generate_agent_prompt","modèle consolidé",EdgeType.INJECT),
    ("tmdd.generate_diagram","REPORT","diagramme threat HTML",EdgeType.REPORT),
    ("tmdd.generate_report","REPORT","rapport TMDD",EdgeType.REPORT),
    ("tmdd.generate_agent_prompt","codegen.unified_system","agent_prompt.txt → UnifiedSystem",EdgeType.INJECT),
    ("tmdd.generate_agent_prompt","CODE_GENERATED","contraintes injectées (fallback direct)",EdgeType.INJECT),
    ("tmdd.generate_agent_prompt","semgrep.write_custom_semgrep_rule","menaces → règles SAST",EdgeType.INJECT),
    ("tmdd.generate_agent_prompt","opa.opa_check","contraintes → politique Rego",EdgeType.INJECT),
    ("codegen.unified_system","CODE_GENERATED","code généré par crewAI+OpenHands",EdgeType.DATA_FLOW),

    # ── SEMGREP ───────────────────────────────────────────────────────────────
    ("semgrep.get_semgrep_rule_schema","semgrep.write_custom_semgrep_rule","schéma → règle",EdgeType.DATA_FLOW),
    ("semgrep.get_abstract_syntax_tree","semgrep.write_custom_semgrep_rule","AST → règle",EdgeType.DATA_FLOW),
    ("semgrep.write_custom_semgrep_rule","semgrep.semgrep_scan","règle custom",EdgeType.DATA_FLOW),
    ("semgrep.write_custom_semgrep_rule","semgrep.semgrep_scan_with_custom_rul","règle custom",EdgeType.DATA_FLOW),
    ("semgrep.write_custom_semgrep_rule","semgrep.semgrep_publish","règle publiée",EdgeType.DATA_FLOW),
    ("semgrep.semgrep_login","semgrep.semgrep_publish","auth",EdgeType.DATA_FLOW),
    ("semgrep.semgrep_mcp","semgrep.semgrep_scan_2","requête MCP inline",EdgeType.DATA_FLOW),
    ("semgrep.semgrep_mcp","semgrep.semgrep_scan_with_custom_rul","requête MCP",EdgeType.DATA_FLOW),
    ("semgrep.semgrep_scan","semgrep.semgrep_findings","scan terminé",EdgeType.QUERY),
    ("semgrep.semgrep_scan","neo4j.create","findings SARIF",EdgeType.STORE),
    ("semgrep.semgrep_scan_with_custom_rul","neo4j.create","findings custom SARIF",EdgeType.STORE),
    ("semgrep.semgrep_scan_sca","neo4j.create","findings SCA",EdgeType.STORE),
    ("semgrep.semgrep_ci","neo4j.create","findings CI SARIF",EdgeType.STORE),
    ("semgrep.semgrep_scan","PRODUCTION","code audité SAST",EdgeType.DATA_FLOW),

    # ── BEARER ────────────────────────────────────────────────────────────────
    ("bearer.bearer_init","bearer.bearer_scan","config bearer.yml",EdgeType.DATA_FLOW),
    ("bearer.bearer_ignore","bearer.bearer_scan","baseline / faux positifs",EdgeType.VALIDATE),
    ("bearer.bearer_scan","bearer.rapport_security","scan complet",EdgeType.DATA_FLOW),
    ("bearer.bearer_scan","bearer.rapport_privacy","scan complet",EdgeType.DATA_FLOW),
    ("bearer.bearer_scan","bearer.rapport_dataflow","scan complet",EdgeType.DATA_FLOW),
    ("bearer.bearer_scan","bearer.rapport_saas","scan complet",EdgeType.DATA_FLOW),
    ("bearer.bearer_scan","bearer.export_sarif","findings",EdgeType.TRANSFORM),
    ("bearer.bearer_scan","bearer.detecteurs_par_langage_detec","détecteurs actifs",EdgeType.QUERY),
    ("bearer.rapport_privacy","neo4j.create","flux PII/RGPD",EdgeType.STORE),
    ("bearer.export_sarif","neo4j.create","SARIF Bearer",EdgeType.STORE),
    ("bearer.bearer_scan","PRODUCTION","code audité privacy",EdgeType.DATA_FLOW),

    # ── CODEQL ────────────────────────────────────────────────────────────────
    ("codeql.codeql_pack_download_install","codeql.codeql_database_analyze","packs requêtes",EdgeType.DATA_FLOW),
    ("codeql.codeql_database_create","codeql.codeql_database_analyze","base CodeQL",EdgeType.DATA_FLOW),
    ("codeql.codeql_query_run","codeql.codeql_database_analyze","requête QL",EdgeType.DATA_FLOW),
    ("codeql.codeql_database_analyze","codeql.suite_security_extended_qls_","base analysée",EdgeType.ANALYZE),
    ("codeql.codeql_database_analyze","codeql.suite_security_and_quality_q","base analysée",EdgeType.ANALYZE),
    ("codeql.codeql_database_analyze","codeql.suite_code_scanning_qls","base analysée",EdgeType.ANALYZE),
    ("codeql.suite_security_extended_qls_","neo4j.create","findings sécurité SARIF",EdgeType.STORE),
    ("codeql.suite_security_and_quality_q","neo4j.create","findings qualité SARIF",EdgeType.STORE),
    ("codeql.suite_code_scanning_qls","neo4j.create","findings GitHub SARIF",EdgeType.STORE),
    ("codeql.codeql_database_analyze","PRODUCTION","code audité sémantique",EdgeType.DATA_FLOW),
]


# ── builder ────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def build() -> ComposabilityGraph:
    """
    Build and return the singleton ComposabilityGraph.
    Cached after first call.
    """
    G = ComposabilityGraph()

    # ── 1. load parsed nodes ──────────────────────────────────────────────────
    nodes_path = _find_nodes_json()
    raw_nodes: list[dict] = json.loads(nodes_path.read_text())

    # ── 2. virtual node definitions ───────────────────────────────────────────
    VIRTUAL_DEFS = [
        dict(id="LEON",          module="virtual", module_name="León AI",
             function="Entrée vocale", description="Interface NL/voix (leon-ai/leon)",
             tag="elicit.input", phase="elicit", type="input",
             io_in="Voix / langage naturel", io_out="requête structurée",
             ref="leon-ai/leon", repo="leon-ai/leon", virtual=True, subsection=None),
        dict(id="CODEBASE",      module="virtual", module_name="Code existant",
             function="Codebase", description="Dépôt de code fourni en entrée",
             tag="elicit.input", phase="elicit", type="input",
             io_in="code source", io_out="fichiers source",
             ref="entrée externe", repo="–", virtual=True, subsection=None),
        dict(id="CODE_GENERATED",module="virtual", module_name="Vibe Coding",
             function="Code généré",
             description="Artefact Cursor/Claude Code avec contraintes TMDD+OPA",
             tag="codegen.output", phase="codegen", type="output",
             io_in="contraintes validées + architecture", io_out="code",
             ref="Cursor / Claude Code", repo="–", virtual=True, subsection=None),
        dict(id="REPORT",        module="virtual", module_name="Rapports",
             function="Rapports unifiés",
             description="Agrège rapports archi/menaces/séquences/audit",
             tag="report.output", phase="report", type="output",
             io_in="artefacts divers", io_out="rapports HTML/Markdown",
             ref="sortie pipeline", repo="–", virtual=True, subsection=None),
        dict(id="PRODUCTION",    module="virtual", module_name="Production",
             function="Déploiement",
             description="Artefact final — code audité validé par le pipeline",
             tag="deploy.output", phase="deploy", type="output",
             io_in="code audité", io_out="déploiement",
             ref="sortie pipeline", repo="–", virtual=True, subsection=None),
    ]

    all_raw = VIRTUAL_DEFS + raw_nodes

    # ── 3. register nodes ─────────────────────────────────────────────────────
    skipped = 0
    for nd in all_raw:
        node_id = nd["id"]
        meta = NodeMeta(
            id          = node_id,
            module      = nd.get("module", ""),
            module_name = nd.get("module_name", ""),
            function    = nd.get("function", ""),
            description = nd.get("description", ""),
            tag         = nd.get("tag", ""),
            phase       = nd.get("phase", ""),
            type        = nd.get("type", ""),
            io_in       = nd.get("io_in", ""),
            io_out      = nd.get("io_out", ""),
            ref         = nd.get("ref", ""),
            repo        = nd.get("repo", ""),
            virtual     = bool(nd.get("virtual", False)),
            subsection  = nd.get("subsection"),
        )
        handler = ALL_HANDLERS.get(node_id)
        G.register(Node(meta, handler))

    logger.info("Registered %d nodes (%d live)", G.node_count,
                sum(1 for n in G.nodes() if n.is_live))

    # ── 4. wire edges ─────────────────────────────────────────────────────────
    bad_edges = 0
    for src, tgt, lbl, etype in RAW_EDGES:
        try:
            G.connect(Edge(source=src, target=tgt, label=lbl, type=etype))
        except KeyError as e:
            logger.warning("Skipping edge %s→%s: %s", src, tgt, e)
            bad_edges += 1

    logger.info("Wired %d edges (%d skipped)", G.edge_count, bad_edges)

    if bad_edges:
        raise RuntimeError(
            f"{bad_edges} edges reference unknown node IDs. "
            "Re-run parse_nodes.py and verify nodes.json."
        )

    return G
