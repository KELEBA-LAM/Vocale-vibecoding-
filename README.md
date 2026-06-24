# nexus_compose

**NEXUS — Module d'orchestration du pipeline de conception logicielle**

Graphe de composabilité unifié : **158 nœuds · 197 arêtes · 14 modules · 10 phases**

---

## Architecture

```
nexus_compose/
├── graph.py          # ComposabilityGraph, Node, Edge, EdgeType, NodeResult
├── registry.py       # build() — câble les 158 nœuds + 197 arêtes
├── drivers.py        # Handlers réels par module (+ stub gracieux si outil absent)
├── orchestrator.py   # Orchestrator — exécution, dry-run, trace, phases, parallèle
├── __init__.py       # API publique
├── __main__.py       # CLI : python -m nexus_compose <cmd>
└── nodes.json        # Métadonnées parsées des 153 fonctions réelles
```

## Pipeline (8 phases → Production)

```
LEON / CODEBASE
    ↓
Phase elicit  : Query2Diagram      → use cases · user stories · UML
    ↓
Phase arch    : LikeC4 · C4InterFlow · Structurizr DSL
                → source de vérité C4 (Context/Container/Component/Deployment)
    ↓
Phase net     : Containerlab       → topologie réseau · microservices · VPN
    ↓
Phase policy  : OPA ← Batfish     → politiques Rego · validation sans déploiement
    ↓
Phase threat  : Threat Dragon · pytm
                → DFD · STRIDE · LINDDUN · CIA · menaces as code
    ↓
Phase graph   : Neo4j              → Knowledge graph unifié
    ↓
Phase codegen : TMDD               → contraintes → Cursor / Claude Code
    ↓
Phase audit   : Semgrep · Bearer · CodeQL
                → SAST · Privacy/RGPD · analyse sémantique
    ↓
REPORT · PRODUCTION
```

## Installation

```bash
pip install -e .                  # core (aucune dépendance obligatoire)
pip install -e ".[all]"           # toutes les dépendances optionnelles
pip install -e ".[neo4j,semgrep]" # sélectif
```

## Utilisation

### Python API

```python
from nexus_compose import build_graph, Orchestrator

G    = build_graph()
orch = Orchestrator(G)

# --- inspecter le graphe ---
print(G.summary())
print(G.list_nodes(module="semgrep"))
print(G.list_nodes(phase="audit"))

path = G.shortest_path("LEON", "PRODUCTION")   # → liste de node_ids

# --- dry-run : voir ce qui s'exécuterait ---
report = orch.dry_run()
print(report)

# --- exécuter un nœud unique ---
result = orch.run_node("semgrep.semgrep_scan", {"target_path": "/mon/projet"})
print(result.data)

# --- exécuter une phase entière ---
pr = orch.run_phase("audit", {"target_path": "/mon/projet"})
print(pr.summary())

# --- pipeline greenfield complet ---
pr = orch.greenfield_pipeline(ctx={"code_path": "/mon/projet"})
print(pr.summary())

# --- pipeline audit seulement ---
pr = orch.audit_only_pipeline("/mon/projet")
print(pr.summary())

# --- pipeline modélisation des menaces ---
pr = orch.threat_model_pipeline(architecture_json)

# --- pipeline validation réseau ---
pr = orch.network_validation_pipeline("topology.clab.yml", "policy.rego")

# --- tracer un chemin source → target ---
trace = orch.trace("LEON", "PRODUCTION")
print(trace.summary())

# --- exécution depuis un point d'entrée ---
pr = orch.run_from("CODEBASE", ctx={"code_path": "."})

# --- exécution parallèle (nœuds indépendants) ---
pr = orch.run_parallel(["semgrep.semgrep_scan", "bearer.bearer_scan"], ctx={...})

# --- injecter un handler live à l'exécution ---
orch.inject("neo4j.create", mon_handler_neo4j)

# --- itérer les phases en ordre ---
for phase, pr in orch.iter_phase_pipelines():
    print(f"{phase}: {pr.summary()}")
```

### CLI

```bash
# stats du graphe
python -m nexus_compose summary

# dry-run complet
python -m nexus_compose dry-run

# dry-run filtré
python -m nexus_compose dry-run --phase audit
python -m nexus_compose dry-run --module semgrep

# exécuter un nœud
python -m nexus_compose run-node semgrep.semgrep_scan --json '{"target_path":"."}'

# exécuter une phase
python -m nexus_compose run-phase audit --json '{"target_path":"."}'

# pipeline depuis un point d'entrée
python -m nexus_compose run-from LEON

# audit d'un dépôt existant
python -m nexus_compose audit /chemin/vers/projet

# tracer un chemin
python -m nexus_compose trace LEON PRODUCTION

# lister les nœuds
python -m nexus_compose list-nodes --module neo4j
python -m nexus_compose list-nodes --phase threat

# lister les phases / modules
python -m nexus_compose list-phases
python -m nexus_compose list-modules

# trouver des chemins entre deux nœuds
python -m nexus_compose paths CODEBASE neo4j.create --max 3
```

## Types d'arêtes

| Type | Couleur | Sémantique |
|------|---------|-----------|
| `data_flow` | bleu | flux de données principal |
| `transform` | vert | conversion de format |
| `validate` | ambre | vérification / assertion |
| `query` | violet | lecture / interrogation |
| `inject` | rose | contrainte → prompt agent/LLM |
| `store` | vert | persistance Neo4j |
| `analyze` | pourpre | analyse sémantique (CodeQL) |
| `simulate` | orange | simulation réseau (Containerlab) |
| `indirect` | gris | bridge à médiation humaine |
| `report` | blanc | sortie rapport |

## Modules (14 + 5 virtuels)

| Module | Nœuds | Rôle |
|--------|-------|------|
| Query2Diagram | 7 | Co-conception NL → diagramme |
| LikeC4 | 28 | Source de vérité architecturale C4 |
| C4InterFlow | 8 | Analyse des flux AaC |
| Structurizr DSL | 9 | DSL workspace/modèles |
| Containerlab | 12 | Topologie réseau |
| Open Policy Agent | 11 | Politiques Rego |
| Batfish | 10 | Validation config réseau |
| OWASP Threat Dragon | 13 | DFD + STRIDE/LINDDUN |
| OWASP pytm | 10 | Threat modeling as code |
| Neo4j | 9 | Knowledge graph unifié |
| TMDD | 8 | Contraintes → agent |
| Semgrep | 12 | SAST + règles custom |
| Bearer | 9 | Privacy / RGPD |
| CodeQL | 7 | Analyse sémantique |
| Virtuels | 5 | LEON · CODEBASE · CODE_GENERATED · REPORT · PRODUCTION |

## Composabilité

Le pipeline est conçu pour être composable. Vous ne partez pas toujours de zéro :

```python
# Vous avez déjà une architecture → sauter Q2D/LikeC4
pr = orch.run_from("c4if.executeaacstrategycommand", ctx={...})

# Vous avez déjà un threat model → sauter jusqu'à TMDD
pr = orch.run_from("tmdd.tmdd_init", ctx={...})

# Vous voulez seulement auditer du code existant
pr = orch.audit_only_pipeline("/path/to/code")

# Pipeline custom avec les nœuds de votre choix
pr = orch.run_pipeline([
    "semgrep.write_custom_semgrep_rule",
    "semgrep.semgrep_scan_with_custom_rul",
    "neo4j.create",
    "REPORT",
], ctx={"threat": {...}, "target_path": "."})
```
