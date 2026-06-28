"""
nexus_compose_patch.exceptions
──────────────────────────────
Exceptions explicites qui REMPLACENT _stub_result().

Au lieu de retourner silencieusement {"_stub": True},
les nœuds indisponibles lèvent une de ces exceptions —
ce qui permet à l'orchestrateur (Leon ou CLI) de signaler
clairement le problème plutôt que de faire semblant de réussir.
"""
from __future__ import annotations


class NexusNodeError(Exception):
    """Classe de base pour toutes les erreurs de nœud Nexus."""
    node_id: str


class NodeUnavailableError(NexusNodeError):
    """
    Levée quand le binaire ou le SDK requis est absent.

    Remplace tous les patterns :
        except Exception as e:
            return _stub_result("module.fn", ctx, str(e))

    Attributs
    ---------
    node_id    : identifiant complet du nœud (ex: "semgrep.semgrep_scan")
    tool       : nom du binaire ou package manquant (ex: "semgrep")
    reason     : explication lisible humain
    install    : commande d'installation suggérée
    doc_url    : URL vers la documentation d'installation
    category   : "missing_binary" | "missing_sdk" | "saas_credentials"
                 | "external_process" | "frontend_only" | "manual_operation"
    """

    INSTALL_HINTS: dict[str, dict] = {
        # ── Outils de scan SAST/SCA ─────────────────────────────────────────
        "semgrep": {
            "install": "pip install semgrep  # ou  brew install semgrep",
            "doc": "https://semgrep.dev/docs/getting-started/",
            "category": "missing_binary",
        },
        "bearer": {
            "install": "brew tap Bearer/tap && brew install bearer  # ou  "
                       "curl -sfL https://raw.githubusercontent.com/Bearer/bearer/main/contrib/install.sh | sh",
            "doc": "https://docs.bearer.com/reference/installation",
            "category": "missing_binary",
        },
        "codeql": {
            "install": "gh extensions install github/gh-codeql  # ou  télécharger depuis "
                       "https://github.com/github/codeql-action/releases",
            "doc": "https://docs.github.com/en/code-security/codeql-cli/getting-started-with-the-codeql-cli",
            "category": "missing_binary",
        },
        # ── Architecture & graphe ────────────────────────────────────────────
        "likec4": {
            "install": "npm install -g @likec4/cli",
            "doc": "https://likec4.dev/docs/getting-started/",
            "category": "missing_binary",
        },
        "structurizr-cli": {
            "install": "brew install structurizr/tap/structurizr-cli  # ou  "
                       "télécharger depuis https://github.com/structurizr/cli/releases",
            "doc": "https://github.com/structurizr/cli",
            "category": "missing_binary",
        },
        "dotnet": {
            "install": "https://dotnet.microsoft.com/download  (SDK .NET 8+)",
            "doc": "https://learn.microsoft.com/en-us/dotnet/core/install/",
            "category": "missing_binary",
        },
        # ── Réseau & politique ───────────────────────────────────────────────
        "containerlab": {
            "install": "bash -c \"$(curl -sL https://get.containerlab.dev)\"",
            "doc": "https://containerlab.dev/install/",
            "category": "missing_binary",
        },
        "opa": {
            "install": "brew install opa  # ou  "
                       "curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static && chmod +x opa",
            "doc": "https://www.openpolicyagent.org/docs/latest/#running-opa",
            "category": "missing_binary",
        },
        # ── SDKs Python ──────────────────────────────────────────────────────
        "pybatfish": {
            "install": "pip install pybatfish",
            "doc": "https://pybatfish.readthedocs.io/",
            "category": "missing_sdk",
        },
        "neo4j": {
            "install": "pip install neo4j",
            "doc": "https://neo4j.com/docs/python-manual/current/",
            "category": "missing_sdk",
        },
        "pytm": {
            "install": "pip install pytm",
            "doc": "https://owasp-pytm.readthedocs.io/",
            "category": "missing_sdk",
        },
        "tmdd": {
            "install": "pip install tmdd  # ou  pip install -e tmdd-main/",
            "doc": "https://github.com/xvnpw/tmdd",
            "category": "missing_binary",
        },
        "q2d": {
            "install": "pip install -e query2diagram-main/",
            "doc": "https://github.com/xvnpw/sec-docs",
            "category": "missing_sdk",
        },
        "openai": {
            "install": "pip install openai  +  exporter OPENAI_API_KEY",
            "doc": "https://platform.openai.com/docs/quickstart",
            "category": "saas_credentials",
        },
        "requests": {
            "install": "pip install requests",
            "doc": "https://docs.python-requests.org/",
            "category": "missing_sdk",
        },
        "jinja2": {
            "install": "pip install jinja2",
            "doc": "https://jinja.palletsprojects.com/",
            "category": "missing_sdk",
        },
    }

    def __init__(
        self,
        node_id: str,
        tool: str = "",
        reason: str = "",
        install: str = "",
        doc_url: str = "",
        category: str = "missing_binary",
    ) -> None:
        self.node_id = node_id
        self.tool = tool or node_id.split(".")[0]

        # Auto-résolution des hints si non fournis
        hint = self.INSTALL_HINTS.get(self.tool, {})
        self.reason   = reason   or f"Outil requis absent : '{self.tool}'"
        self.install  = install  or hint.get("install", f"Installer '{self.tool}'")
        self.doc_url  = doc_url  or hint.get("doc",     "")
        self.category = category or hint.get("category", "missing_binary")

        super().__init__(
            f"[{node_id}] Nœud indisponible — {self.reason}\n"
            f"  Installation : {self.install}"
            + (f"\n  Documentation : {self.doc_url}" if self.doc_url else "")
        )

    def to_dict(self) -> dict:
        """Représentation structurée pour l'API et les logs."""
        return {
            "_unavailable": True,
            "node_id":      self.node_id,
            "tool":         self.tool,
            "reason":       self.reason,
            "install":      self.install,
            "doc_url":      self.doc_url,
            "category":     self.category,
        }


class NodeExecutionError(NexusNodeError):
    """
    Levée quand le nœud peut démarrer mais échoue pendant l'exécution.
    L'outil est présent mais produit une erreur (code retour != 0, parsing, etc.)
    """

    def __init__(self, node_id: str, error: str, exit_code: int = -1) -> None:
        self.node_id   = node_id
        self.error     = error
        self.exit_code = exit_code
        super().__init__(f"[{node_id}] Échec d'exécution (code {exit_code}) : {error}")

    def to_dict(self) -> dict:
        return {
            "_execution_error": True,
            "node_id":          self.node_id,
            "error":            self.error,
            "exit_code":        self.exit_code,
        }


class NodeExternalProcessError(NexusNodeError):
    """
    Levée pour les nœuds qui nécessitent un processus long-running externe
    (serveur OPA, LikeC4 serve, etc.).
    Ne peut pas s'exécuter inline — doit être lancé manuellement.
    """

    def __init__(self, node_id: str, command: str, reason: str = "") -> None:
        self.node_id = node_id
        self.command = command
        self.reason  = reason or "Processus long-running — lancer manuellement"
        super().__init__(
            f"[{node_id}] Processus externe requis\n"
            f"  Commande : {command}\n"
            f"  Raison   : {self.reason}"
        )

    def to_dict(self) -> dict:
        return {
            "_external_process": True,
            "node_id":           self.node_id,
            "command":           self.command,
            "reason":            self.reason,
        }


class NodeFrontendOnlyError(NexusNodeError):
    """
    Levée pour les nœuds qui s'exécutent côté navigateur (Vue.js/X6.js).
    Ces nœuds ne peuvent pas être appelés via une API server-side.
    """

    def __init__(self, node_id: str, frontend_source: str, reason: str = "") -> None:
        self.node_id         = node_id
        self.frontend_source = frontend_source
        self.reason          = reason or "Module JavaScript côté navigateur uniquement"
        super().__init__(
            f"[{node_id}] Frontend uniquement — {self.reason}\n"
            f"  Source : {frontend_source}"
        )

    def to_dict(self) -> dict:
        return {
            "_frontend_only":  True,
            "node_id":         self.node_id,
            "frontend_source": self.frontend_source,
            "reason":          self.reason,
        }


class NodeSaasCredentialsError(NexusNodeError):
    """
    Levée pour les nœuds qui requièrent des credentials SaaS
    (Semgrep Cloud, LeanIX, etc.).
    """

    def __init__(self, node_id: str, service: str, env_vars: list[str]) -> None:
        self.node_id  = node_id
        self.service  = service
        self.env_vars = env_vars
        super().__init__(
            f"[{node_id}] Credentials SaaS manquants pour '{service}'\n"
            f"  Variables d'environnement requises : {', '.join(env_vars)}"
        )

    def to_dict(self) -> dict:
        return {
            "_saas_required": True,
            "node_id":        self.node_id,
            "service":        self.service,
            "env_vars":       self.env_vars,
        }
