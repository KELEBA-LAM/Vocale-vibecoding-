"""
test/test_unified_system.py
────────────────────────────
Tests unitaires pour unified_system.bridge et le bootstrap des sous-systèmes.

DESIGN — 100 % stub-safe :
  • Aucun serveur OpenHands réel requis.
  • Les imports crewAI / openmanus_rl / openhands sont mockés si absents
    (les dépendances sont optionnelles en dehors d'un environnement
    fullstack). Les tests sont décorés @pytest.mark.unified_full
    quand ils nécessitent les vraies bibliothèques.
  • La suite reste dans le job CI standard (continue-on-error si les libs
    manquent) et n'empêche jamais le passage de la suite nexus_compose.

Run :
    pytest test/test_unified_system.py -v
    pytest test/test_unified_system.py -v -m "not unified_full"
"""

from __future__ import annotations

import importlib
import os
import sys
import types
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── Détection des dépendances optionnelles ─────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
UNIFIED_DIR = REPO_ROOT / "unified_system"

HAS_CREWAI = importlib.util.find_spec("crewai") is not None
HAS_OPENHANDS = importlib.util.find_spec("openhands") is not None
HAS_OPENMANUS = (UNIFIED_DIR / "openmanus_rl" / "__init__.py").exists()
HAS_FULL_STACK = HAS_CREWAI and HAS_OPENHANDS and HAS_OPENMANUS

requires_full_stack = pytest.mark.skipif(
    not HAS_FULL_STACK,
    reason="crewAI / OpenHands / OpenManus-RL non installés — run bootstrap.sh d'abord",
)
unified_full = pytest.mark.unified_full


# ── Stubs pour les imports optionnels ─────────────────────────────────────────
def _mock_crewai():
    """Injecte des stubs crewAI minimaux dans sys.modules."""
    crewai = types.ModuleType("crewai")

    class Agent:
        def __init__(self, **kw): self.__dict__.update(kw)

    class Task:
        def __init__(self, **kw): self.__dict__.update(kw)

    class Crew:
        def __init__(self, agents=None, tasks=None, **kw):
            self.agents = agents or []
            self.tasks = tasks or []
        def kickoff(self, inputs=None):
            return "stub-crew-output"

    crewai.Agent = Agent
    crewai.Task = Task
    crewai.Crew = Crew
    crewai.tools = types.ModuleType("crewai.tools")
    crewai.tools.openhands_tool = types.ModuleType("crewai.tools.openhands_tool")

    class OpenHandsTask:
        def __init__(self, **kw): pass
    crewai.tools.openhands_tool.OpenHandsTask = OpenHandsTask

    sys.modules.setdefault("crewai", crewai)
    sys.modules.setdefault("crewai.tools", crewai.tools)
    sys.modules.setdefault("crewai.tools.openhands_tool", crewai.tools.openhands_tool)
    return crewai


def _mock_openmanus():
    """Injecte des stubs openmanus_rl minimaux dans sys.modules."""
    openmanus = types.ModuleType("openmanus_rl")
    engines = types.ModuleType("openmanus_rl.engines")
    openai_mod = types.ModuleType("openmanus_rl.engines.openai")

    class CrewAIEngine:
        def __init__(self, crew_factory=None, **kw):
            self._crew_factory = crew_factory
        def __call__(self, prompt: str = "", **kw) -> str:
            return f"stub-engine-output: {prompt[:40]}"

    openai_mod.CrewAIEngine = CrewAIEngine
    openmanus.engines = engines
    engines.openai = openai_mod

    multi_turn = types.ModuleType("openmanus_rl.multi_turn_rollout")
    tool_integ = types.ModuleType("openmanus_rl.multi_turn_rollout.tool_integration")

    class SSRFSafeToolRegistry:
        pass
    tool_integ.SSRFSafeToolRegistry = SSRFSafeToolRegistry
    multi_turn.tool_integration = tool_integ
    openmanus.multi_turn_rollout = multi_turn

    for name, mod in [
        ("openmanus_rl", openmanus),
        ("openmanus_rl.engines", engines),
        ("openmanus_rl.engines.openai", openai_mod),
        ("openmanus_rl.multi_turn_rollout", multi_turn),
        ("openmanus_rl.multi_turn_rollout.tool_integration", tool_integ),
    ]:
        sys.modules.setdefault(name, mod)
    return openmanus


# ── Fixture : import bridge avec stubs si nécessaire ──────────────────────────
@pytest.fixture(scope="module")
def bridge_module():
    """Charge unified_system.bridge, en injectant des stubs si besoin."""
    if not HAS_CREWAI:
        _mock_crewai()
    if not HAS_OPENMANUS:
        _mock_openmanus()

    # S'assurer que unified_system est dans sys.path
    unified_parent = str(REPO_ROOT)
    if unified_parent not in sys.path:
        sys.path.insert(0, unified_parent)

    try:
        if "unified_system.bridge" in sys.modules:
            del sys.modules["unified_system.bridge"]
        import unified_system.bridge as bridge
        return bridge
    except ImportError as e:
        pytest.skip(f"unified_system.bridge non importable : {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. ZIPS BUNDLÉS — présence et intégrité
# ══════════════════════════════════════════════════════════════════════════════

class TestBundledZips:
    """Vérifie que les 18 zips sont présents et lisibles dans le dépôt."""

    ROOT_ZIPS = [
        "Leon AI.zip", "neo4j.zip", "query2diagram.zip", "Batfish.zip",
        "semgrep.zip", "likec4.zip", "pytm.zip", "codeql.zip", "dsl.zip",
        "opa.zip", "tmdd.zip", "threat-dragon.zip", "containerlab.zip",
        "C4InterFlow.zip", "bearer.zip",
    ]
    UNIFIED_ZIPS = ["crewAI.zip", "OpenManus-RL.zip", "OpenHands.zip"]

    @pytest.mark.parametrize("name", ROOT_ZIPS)
    def test_root_zip_present(self, name):
        path = REPO_ROOT / name
        assert path.exists(), f"Zip manquant : {name}"
        assert path.stat().st_size > 0, f"Zip vide : {name}"

    @pytest.mark.parametrize("name", UNIFIED_ZIPS)
    def test_unified_zip_present(self, name):
        path = UNIFIED_DIR / name
        assert path.exists(), f"Zip unified_system manquant : {name}"
        assert path.stat().st_size > 0, f"Zip vide : {name}"

    def test_all_15_root_zips_present(self):
        missing = [n for n in self.ROOT_ZIPS if not (REPO_ROOT / n).exists()]
        assert not missing, f"Zips manquants : {missing}"

    def test_all_3_unified_zips_present(self):
        missing = [n for n in self.UNIFIED_ZIPS if not (UNIFIED_DIR / n).exists()]
        assert not missing, f"Zips unified_system manquants : {missing}"

    def test_total_18_zips(self):
        total = len(self.ROOT_ZIPS) + len(self.UNIFIED_ZIPS)
        assert total == 18

    def test_zip_files_are_valid_zip_format(self):
        """Vérifie que chaque zip commence par la signature PK (magic bytes)."""
        import zipfile
        for name in self.ROOT_ZIPS:
            path = REPO_ROOT / name
            if path.exists():
                assert zipfile.is_zipfile(path), f"Fichier corrompu (pas un ZIP valide) : {name}"

    def test_unified_zips_valid_format(self):
        import zipfile
        for name in self.UNIFIED_ZIPS:
            path = UNIFIED_DIR / name
            if path.exists():
                assert zipfile.is_zipfile(path), f"Zip corrompu : {name}"


# ══════════════════════════════════════════════════════════════════════════════
# 2. BOOTSTRAP — extraction des sous-systèmes
# ══════════════════════════════════════════════════════════════════════════════

class TestBootstrap:
    """Teste l'extraction unitaire des zips (ne nécessite pas que bootstrap.sh
    ait déjà tourné — utilise des répertoires temporaires isolés)."""

    def test_leon_zip_extracts_to_expected_structure(self, tmp_path):
        import zipfile
        zip_path = REPO_ROOT / "Leon AI.zip"
        if not zip_path.exists():
            pytest.skip("Leon AI.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        # La structure GitHub est outer/outer/...
        roots = {n.split("/")[0] for n in names if "/" in n}
        assert "leon-develop" in roots, \
            f"Structure inattendue dans Leon AI.zip. Racines trouvées : {roots}"

    def test_pytm_zip_contains_setup_or_pyproject(self):
        import zipfile
        zip_path = REPO_ROOT / "pytm.zip"
        if not zip_path.exists():
            pytest.skip("pytm.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        has_setup = any("setup.py" in n or "pyproject.toml" in n for n in names)
        assert has_setup, "pytm.zip ne contient pas de setup.py / pyproject.toml"

    def test_q2d_zip_contains_setup_or_pyproject(self):
        import zipfile
        zip_path = REPO_ROOT / "query2diagram.zip"
        if not zip_path.exists():
            pytest.skip("query2diagram.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        has_setup = any("setup.py" in n or "pyproject.toml" in n for n in names)
        assert has_setup

    def test_tmdd_zip_contains_setup_or_pyproject(self):
        import zipfile
        zip_path = REPO_ROOT / "tmdd.zip"
        if not zip_path.exists():
            pytest.skip("tmdd.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        has_setup = any("setup.py" in n or "pyproject.toml" in n for n in names)
        assert has_setup

    def test_openhands_zip_contains_pyproject(self):
        import zipfile
        zip_path = UNIFIED_DIR / "OpenHands.zip"
        if not zip_path.exists():
            pytest.skip("OpenHands.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("pyproject.toml" in n for n in names), \
            "OpenHands.zip ne contient pas de pyproject.toml"

    def test_openhands_zip_contains_dockerfile(self):
        import zipfile
        zip_path = UNIFIED_DIR / "OpenHands.zip"
        if not zip_path.exists():
            pytest.skip("OpenHands.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("containers/app/Dockerfile" in n for n in names), \
            "OpenHands.zip ne contient pas containers/app/Dockerfile"

    def test_crewai_zip_contains_pyproject(self):
        import zipfile
        zip_path = UNIFIED_DIR / "crewAI.zip"
        if not zip_path.exists():
            pytest.skip("crewAI.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("pyproject.toml" in n for n in names)

    def test_opa_zip_contains_go_module(self):
        import zipfile
        zip_path = REPO_ROOT / "opa.zip"
        if not zip_path.exists():
            pytest.skip("opa.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any(n.endswith("/go.mod") and n.count("/") == 2 for n in names), \
            "opa.zip ne contient pas go.mod à la racine du module"

    def test_bearer_zip_contains_go_module(self):
        import zipfile
        zip_path = REPO_ROOT / "bearer.zip"
        if not zip_path.exists():
            pytest.skip("bearer.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any(n.endswith("/go.mod") and n.count("/") == 2 for n in names)

    def test_c4interflow_zip_contains_cli_csproj(self):
        import zipfile
        zip_path = REPO_ROOT / "C4InterFlow.zip"
        if not zip_path.exists():
            pytest.skip("C4InterFlow.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("C4InterFlow.Cli.csproj" in n for n in names)

    def test_bootstrap_script_is_executable_or_has_shebang(self):
        bs = REPO_ROOT / "scripts" / "bootstrap.sh"
        assert bs.exists(), "scripts/bootstrap.sh manquant"
        content = bs.read_text()
        assert content.startswith("#!/"), "bootstrap.sh sans shebang"
        assert "unzip" in content, "bootstrap.sh ne contient pas de commande unzip"
        assert "pip install" in content, "bootstrap.sh ne contient pas pip install"

    def test_launch_script_exists_and_calls_bootstrap(self):
        ls = REPO_ROOT / "scripts" / "launch.sh"
        assert ls.exists(), "scripts/launch.sh manquant"
        content = ls.read_text()
        assert "bootstrap.sh" in content
        assert "docker compose" in content


# ══════════════════════════════════════════════════════════════════════════════
# 3. UNIFIED_SYSTEM.BRIDGE — config et API (stub-safe)
# ══════════════════════════════════════════════════════════════════════════════

class TestBridgeConfig:

    def test_unified_system_config_defaults(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig()
        assert cfg.openhands_base_url == "http://localhost:3000"
        assert cfg.crewai_llm_model == "gpt-4o-mini"
        assert cfg.rl_max_steps == 1000
        assert cfg.rl_batch_size == 4

    def test_unified_system_config_from_env(self, bridge_module, monkeypatch):
        monkeypatch.setenv("OH_BASE_URL", "http://oh-test:9999")
        monkeypatch.setenv("CREWAI_LLM_MODEL", "gpt-4-turbo")
        monkeypatch.setenv("RL_MAX_STEPS", "500")
        monkeypatch.setenv("RL_BATCH_SIZE", "8")
        monkeypatch.setenv("OH_TIMEOUT", "60")

        cfg = bridge_module.UnifiedSystemConfig.from_env()
        assert cfg.openhands_base_url == "http://oh-test:9999"
        assert cfg.crewai_llm_model == "gpt-4-turbo"
        assert cfg.rl_max_steps == 500
        assert cfg.rl_batch_size == 8
        assert cfg.openhands_timeout == 60

    def test_unified_system_config_from_env_defaults(self, bridge_module, monkeypatch):
        for key in ["OH_BASE_URL", "CREWAI_LLM_MODEL", "RL_MAX_STEPS", "RL_BATCH_SIZE"]:
            monkeypatch.delenv(key, raising=False)
        cfg = bridge_module.UnifiedSystemConfig.from_env()
        assert cfg.rl_max_steps == 1000
        assert cfg.rl_batch_size == 4

    def test_ssrf_protection_enabled_by_default(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig()
        assert cfg.enable_ssrf_protection is True

    def test_reward_allocation_default(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig()
        assert cfg.rl_reward_allocation == "last_token"

    def test_config_is_dataclass(self, bridge_module):
        from dataclasses import fields
        f_names = {f.name for f in fields(bridge_module.UnifiedSystemConfig)}
        assert "openhands_base_url" in f_names
        assert "crewai_llm_model" in f_names
        assert "rl_max_steps" in f_names
        assert "enable_ssrf_protection" in f_names


class TestUnifiedSystemInstantiation:

    def test_from_env_class_method_exists(self, bridge_module):
        assert hasattr(bridge_module.UnifiedSystem, "from_env")
        assert callable(bridge_module.UnifiedSystem.from_env)

    def test_unified_system_init_with_config(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig(
            openhands_base_url="http://stub:1234",
            rl_max_steps=10,
        )
        us = bridge_module.UnifiedSystem(config=cfg)
        assert us.config.openhands_base_url == "http://stub:1234"
        assert us.config.rl_max_steps == 10

    def test_unified_system_has_crew(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        assert hasattr(us, "crew")

    def test_unified_system_has_engine(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        assert hasattr(us, "engine")

    def test_custom_crew_factory_is_used(self, bridge_module):
        """Un crew_factory personnalisé doit remplacer le crew par défaut."""
        sentinel_crew = object()
        us = bridge_module.UnifiedSystem(crew_factory=lambda: sentinel_crew)
        assert us.crew is sentinel_crew

    def test_ssrf_disabled_no_tool_registry(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig(enable_ssrf_protection=False)
        us = bridge_module.UnifiedSystem(config=cfg)
        assert us.tool_registry is None

    def test_ssrf_enabled_creates_registry(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig(enable_ssrf_protection=True)
        us = bridge_module.UnifiedSystem(config=cfg)
        assert us.tool_registry is not None


class TestUnifiedSystemRunTask:

    def test_run_task_returns_string(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        result = us.run_task("Écrire un hello world en Python")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_run_task_empty_instruction(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        result = us.run_task("")
        assert isinstance(result, str)

    def test_run_task_delegates_to_engine(self, bridge_module):
        """run_task doit appeler engine(prompt=...) sans wrap supplémentaire."""
        captured = {}
        class SpyEngine:
            def __call__(self, prompt="", **kw):
                captured["prompt"] = prompt
                return "spy-output"

        us = bridge_module.UnifiedSystem()
        us.engine = SpyEngine()
        us.run_task("Test instruction XYZ")
        assert captured.get("prompt") == "Test instruction XYZ"


class TestUnifiedSystemHealthCheck:

    def test_health_check_returns_dict(self, bridge_module):
        us = bridge_module.UnifiedSystem(
            config=bridge_module.UnifiedSystemConfig(
                openhands_base_url="http://localhost:99999"
            )
        )
        status = us.health_check()
        assert isinstance(status, dict)

    def test_health_check_has_openhands_key(self, bridge_module):
        us = bridge_module.UnifiedSystem(
            config=bridge_module.UnifiedSystemConfig(
                openhands_base_url="http://localhost:99999"
            )
        )
        status = us.health_check()
        assert "openhands" in status

    def test_health_check_has_crewai_key(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "crewai" in status

    def test_health_check_has_rl_engine_key(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "rl_engine" in status

    def test_health_check_openhands_error_when_unreachable(self, bridge_module):
        """L'état OpenHands doit signaler l'erreur sans lever d'exception."""
        us = bridge_module.UnifiedSystem(
            config=bridge_module.UnifiedSystemConfig(
                openhands_base_url="http://127.0.0.1:19999"  # rien n'écoute ici
            )
        )
        status = us.health_check()
        assert "error" in status["openhands"].lower() or "HTTP" in status["openhands"]

    def test_health_check_crewai_ok_when_crew_exists(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "error" not in status["crewai"]

    def test_health_check_rl_ok_when_engine_exists(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "error" not in status["rl_engine"]


class TestBuildRlEnvConfig:

    def test_build_rl_env_config_returns_dict(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        cfg = us.build_rl_env_config()
        assert isinstance(cfg, dict)

    def test_build_rl_env_config_has_env_key(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        cfg = us.build_rl_env_config()
        assert "env" in cfg
        assert "data" in cfg
        assert "algorithm" in cfg

    def test_build_rl_env_config_env_name(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        cfg = us.build_rl_env_config()
        assert cfg["env"]["env_name"] == "openhands"

    def test_build_rl_env_config_reward_allocation(self, bridge_module):
        cfg_obj = bridge_module.UnifiedSystemConfig(rl_reward_allocation="uniform_positive")
        us = bridge_module.UnifiedSystem(config=cfg_obj)
        cfg = us.build_rl_env_config()
        assert cfg["algorithm"]["reward_allocation"] == "uniform_positive"

    def test_build_rl_env_config_batch_size_coherent(self, bridge_module):
        cfg_obj = bridge_module.UnifiedSystemConfig(rl_batch_size=8)
        us = bridge_module.UnifiedSystem(config=cfg_obj)
        cfg = us.build_rl_env_config()
        assert cfg["data"]["train_batch_size"] == 8
        assert cfg["data"]["val_batch_size"] == 2  # max(1, 8//4)

    def test_build_rl_env_config_batch_size_1_gives_val_1(self, bridge_module):
        cfg_obj = bridge_module.UnifiedSystemConfig(rl_batch_size=1)
        us = bridge_module.UnifiedSystem(config=cfg_obj)
        cfg = us.build_rl_env_config()
        assert cfg["data"]["val_batch_size"] == 1  # max(1, 0) = 1


# ══════════════════════════════════════════════════════════════════════════════
# 4. RÉGRESSIONS UNIFIED_SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class TestUnifiedSystemRegressions:

    def test_bridge_py_exists_in_repo(self):
        bridge_path = UNIFIED_DIR / "bridge.py"
        assert bridge_path.exists(), "unified_system/bridge.py manquant"

    def test_bridge_py_is_nonempty(self):
        bridge_path = UNIFIED_DIR / "bridge.py"
        assert bridge_path.stat().st_size > 100, "unified_system/bridge.py semble vide"

    def test_bridge_py_defines_unified_system_class(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "class UnifiedSystem" in content

    def test_bridge_py_defines_unified_system_config(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "class UnifiedSystemConfig" in content

    def test_bridge_py_defines_run_task_method(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "def run_task" in content

    def test_bridge_py_defines_health_check_method(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "def health_check" in content

    def test_bridge_py_defines_from_env_class_method(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "def from_env" in content

    def test_codegen_unified_system_handler_wired_in_nexus(self):
        """
        Régression : le nœud codegen.unified_system doit être câblé dans le
        graphe nexus_compose. Ce test vérifie que le correctif registry.py
        survit à l'ajout du système unifié.
        """
        from nexus_compose import build_graph
        G = build_graph()
        n = G.node("codegen.unified_system")
        assert n is not None
        assert n.is_live, "codegen.unified_system doit avoir un handler live"

    def test_orchestrator_threat_model_pipeline_uses_unified_system(self):
        """
        Vérifie que threat_model_pipeline exécute bien codegen.unified_system.
        """
        from nexus_compose import build_graph, Orchestrator
        G = build_graph()
        orch = Orchestrator(G)
        pr = orch.threat_model_pipeline({"elements": [], "relationships": []})
        executed = {s.node_id for s in pr.steps}
        assert "codegen.unified_system" in executed


# ══════════════════════════════════════════════════════════════════════════════
# 5. TESTS NÉCESSITANT LE STACK COMPLET (skipés en CI si libs absentes)
# ══════════════════════════════════════════════════════════════════════════════

@requires_full_stack
@unified_full
class TestFullStackIntegration:
    """
    Ces tests ne tournent que si crewAI + OpenHands + OpenManus-RL sont tous
    installés depuis leurs zips locaux (bootstrap.sh --fullstack).
    Marqués unified_full pour être excluables facilement.
    """

    def test_real_crewai_crew_creation(self, bridge_module):
        us = bridge_module.UnifiedSystem.from_env()
        assert len(us.crew.agents) >= 1
        assert len(us.crew.tasks) >= 1

    def test_real_engine_is_crewai_engine(self, bridge_module):
        from openmanus_rl.engines.openai import CrewAIEngine
        us = bridge_module.UnifiedSystem.from_env()
        assert isinstance(us.engine, CrewAIEngine)

    def test_real_tool_registry_is_ssrf_safe(self, bridge_module):
        from openmanus_rl.multi_turn_rollout.tool_integration import SSRFSafeToolRegistry
        us = bridge_module.UnifiedSystem.from_env()
        assert isinstance(us.tool_registry, SSRFSafeToolRegistry)
