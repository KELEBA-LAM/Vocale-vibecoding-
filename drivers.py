"""
nexus_compose.drivers
─────────────────────
One handler-dict per tool module. Each key matches the function-name part of
a node id (everything after the first dot).

Handler signature:  def fn(ctx: dict) -> dict

All handlers degrade gracefully: if the tool binary / SDK is absent the
function logs a warning and returns a stub result rather than crashing.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# ── helpers ───────────────────────────────────────────────────────────────────

def _cli(cmd: list[str], input_data: str | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, input=input_data, **kw)

def _require(binary: str) -> str:
    path = shutil.which(binary)
    if not path:
        raise FileNotFoundError(
            f"'{binary}' not found in PATH. Install the tool to enable live execution."
        )
    return path

def _stub_result(node_fn: str, ctx: dict, note: str = "") -> dict:
    logger.info("[STUB] %s%s", node_fn, f" — {note}" if note else "")
    return {"_stub": True, "_fn": node_fn, "ctx": ctx}

# ══════════════════════════════════════════════════════════════════════════════
#  1. QUERY2DIAGRAM
# ══════════════════════════════════════════════════════════════════════════════

def _q2d_generate(ctx: dict) -> dict:
    try:
        _require("python")
        cp  = ctx.get("code_path", ".")
        q   = ctx.get("question", "")
        model = ctx.get("model", "gpt-4o")
        r = _cli(["python", "-m", "q2d", "generate", cp, "-q", q, "--model", model])
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)
    except Exception as e:
        return _stub_result("q2d.generate", ctx, str(e))

def _q2d_traverse(ctx: dict) -> dict:
    try:
        _require("python")
        cp = ctx.get("code_path", ".")
        r  = _cli(["python", "-m", "q2d", "traverse", cp])
        return {"files": r.stdout.splitlines()}
    except Exception as e:
        return _stub_result("q2d.traverse_project", ctx, str(e))

def _q2d_convert(ctx: dict) -> dict:
    graph = ctx.get("graph_json") or ctx
    try:
        _require("python")
        r = _cli(["python", "-m", "q2d", "convert", "--fmt", ctx.get("fmt", "plantuml")],
                 input_data=json.dumps(graph))
        return {"diagram": r.stdout}
    except Exception as e:
        return _stub_result("q2d.convert_graph", ctx, str(e))

def _q2d_fix_format(ctx: dict) -> dict:
    try:
        _require("python")
        r = _cli(["python", "-m", "q2d", "fix-format"], input_data=json.dumps(ctx))
        return json.loads(r.stdout)
    except Exception as e:
        return _stub_result("q2d.fix_format", ctx, str(e))

def _q2d_migration(ctx: dict) -> dict:
    return _stub_result("q2d.migration", ctx, "format migration — run manually")

def _q2d_similar(ctx: dict) -> dict:
    return _stub_result("q2d.find_similar_items", ctx, "Jaccard dedup — no binary")

def _q2d_llm(ctx: dict) -> dict:
    try:
        import openai
        client = openai.OpenAI(api_key=ctx.get("api_key") or os.environ.get("OPENAI_API_KEY"))
        resp = client.chat.completions.create(
            model=ctx.get("model", "gpt-4o"),
            messages=ctx.get("messages", [{"role":"user","content":ctx.get("prompt","")}])
        )
        return {"text": resp.choices[0].message.content}
    except Exception as e:
        return _stub_result("q2d.openaiengine_generate", ctx, str(e))



def _q2d_convert_str_graph(ctx: dict) -> dict:
    """convert_str_graph(str, GraphConvertConfig) — shortcut: migration + convert_graph in one call."""
    try:
        from q2d.graph_to_plantuml import convert_str_graph, GraphConvertConfig
        graph_str = ctx.get("graph_str", "")
        cfg = GraphConvertConfig(**ctx.get("convert_config", {}))
        result = convert_str_graph(graph_str, cfg)
        return {"diagram": result, "format": cfg.output_format if hasattr(cfg, "output_format") else "plantuml"}
    except Exception as e:
        return _stub_result("q2d.convert_str_graph", ctx, str(e))

Q2D_HANDLERS = {
    "generate":               _q2d_generate,
    "traverse_project":       _q2d_traverse,
    "convert_graph":          _q2d_convert,
    "fix_format":             _q2d_fix_format,
    "migration":              _q2d_migration,
    "find_similar_items":     _q2d_similar,
    "openaiengine_generate":  _q2d_llm,
}

# ══════════════════════════════════════════════════════════════════════════════
#  2. LIKEC4
# ══════════════════════════════════════════════════════════════════════════════

def _lc4_build(ctx: dict) -> dict:
    try:
        w = ctx.get("workspace", ".")
        r = _cli([_require("likec4"), "build", w])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("likec4.likec4_build", ctx, str(e))

def _lc4_validate(ctx: dict) -> dict:
    try:
        w = ctx.get("workspace", ".")
        r = _cli([_require("likec4"), "validate", w])
        return {"valid": r.returncode == 0, "output": r.stdout}
    except Exception as e:
        return _stub_result("likec4.likec4_validate", ctx, str(e))

def _lc4_export_json(ctx: dict) -> dict:
    try:
        w   = ctx.get("workspace", ".")
        out = ctx.get("output",    "architecture.json")
        r   = _cli([_require("likec4"), "export", "json", w, "-o", out])
        if r.returncode == 0 and Path(out).exists():
            return json.loads(Path(out).read_text())
        raise RuntimeError(r.stderr)
    except Exception as e:
        return _stub_result("likec4.likec4_export_json", ctx, str(e))

def _lc4_codegen(ctx: dict) -> dict:
    try:
        w   = ctx.get("workspace", ".")
        out = ctx.get("output", "src/generated")
        r   = _cli([_require("likec4"), "gen", "model", w, "-o", out])
        return {"exit_code": r.returncode, "output_dir": out}
    except Exception as e:
        return _stub_result("likec4.likec4_codegen_model", ctx, str(e))

def _lc4_mcp_call(tool_name: str, params: dict, workspace: str = ".") -> dict:
    """Send a single MCP tool call to the LikeC4 LSP server via stdio JSON-RPC."""
    import subprocess, threading, uuid
    req_id  = str(uuid.uuid4())[:8]
    request = json.dumps({
        "jsonrpc": "2.0", "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": params},
    })
    header = f"Content-Length: {len(request)}\r\n\r\n"
    try:
        proc = subprocess.Popen(
            [_require("likec4"), "mcp", workspace],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        # LikeC4 LSP needs an initialize handshake first
        init_req = json.dumps({
            "jsonrpc": "2.0", "id": "init",
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {}, "clientInfo": {"name": "nexus"}},
        })
        init_hdr = f"Content-Length: {len(init_req)}\r\n\r\n"
        notif = json.dumps({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
        notif_hdr = f"Content-Length: {len(notif)}\r\n\r\n"
        full_input = init_hdr + init_req + notif_hdr + notif + header + request
        out, _ = proc.communicate(input=full_input, timeout=15)
        # Parse last JSON-RPC response
        responses = [ln for ln in out.split("\r\n") if ln.startswith("{")]
        for r_str in reversed(responses):
            try:
                r = json.loads(r_str)
                if r.get("id") == req_id:
                    return r.get("result", r)
            except json.JSONDecodeError:
                continue
        return {"raw": out[:500], "note": "response parse fallback"}
    except Exception as e:
        return {"error": str(e), "tool": tool_name, "params": params}


def _lc4_mcp_start(ctx: dict) -> dict:
    """Start MCP server: likec4 lsp --stdio <workspace>."""
    w = ctx.get("workspace", ".")
    return {"command": f"likec4 mcp {w}",
            "protocol": "MCP/stdio JSON-RPC 2.0",
            "note": "Use _lc4_mcp_call() for individual tool calls."}


def _lc4_query_graph(ctx: dict) -> dict:
    return _lc4_mcp_call("query-graph", {"elementId": ctx.get("element_id", "")},
                         ctx.get("workspace", "."))


def _lc4_read_element(ctx: dict) -> dict:
    return _lc4_mcp_call("read-element", {"elementId": ctx.get("element_id", "")},
                         ctx.get("workspace", "."))


def _lc4_find_rel(ctx: dict) -> dict:
    return _lc4_mcp_call("find-relationship-paths",
                         {"fromId": ctx.get("from_id", ""),
                          "toId":   ctx.get("to_id",   "")},
                         ctx.get("workspace", "."))


def _lc4_read_depl(ctx: dict) -> dict:
    return _lc4_mcp_call("read-deployment",
                         {"environmentId": ctx.get("environment_id", "")},
                         ctx.get("workspace", "."))


def _lc4_read_view(ctx: dict) -> dict:
    return _lc4_mcp_call("read-view",
                         {"viewId": ctx.get("view_id", "")},
                         ctx.get("workspace", "."))


def _lc4_read_project_summary(ctx: dict) -> dict:
    return _lc4_mcp_call("read-project-summary", {}, ctx.get("workspace", "."))


def _lc4_subgraph_summary(ctx: dict) -> dict:
    return _lc4_mcp_call("subgraph-summary",
                         {"elementId": ctx.get("element_id", ""),
                          "depth":     ctx.get("depth", 2)},
                         ctx.get("workspace", "."))


def _lc4_query_incomers(ctx: dict) -> dict:
    return _lc4_mcp_call("query-incomers-graph",
                         {"elementId": ctx.get("element_id", "")},
                         ctx.get("workspace", "."))


def _lc4_query_by_tags(ctx: dict) -> dict:
    return _lc4_mcp_call("query-by-tags",
                         {"tags": ctx.get("tags", [])},
                         ctx.get("workspace", "."))


def _lc4_query_by_metadata(ctx: dict) -> dict:
    """MCP: query-by-metadata — filter by key/value/matchMode (Phase 2 UC-02)."""
    return _lc4_mcp_call("query-by-metadata",
                         {"key":       ctx.get("key"),
                          "value":     ctx.get("value"),
                          "matchMode": ctx.get("match_mode", "exact")},
                         ctx.get("workspace", "."))


def _lc4_search_element(ctx: dict) -> dict:
    return _lc4_mcp_call("search-element",
                         {"query": ctx.get("query", "")},
                         ctx.get("workspace", "."))


def _lc4_element_diff(ctx: dict) -> dict:
    return _lc4_mcp_call("element-diff",
                         {"elementId": ctx.get("element_id", ""),
                          "refCommit": ctx.get("ref_commit", "HEAD~1")},
                         ctx.get("workspace", "."))


def _lc4_apply_layout(ctx: dict) -> dict:
    return _lc4_mcp_call("apply-semantic-layout",
                         {"viewId": ctx.get("view_id", "")},
                         ctx.get("workspace", "."))


def _lc4_list_projects(ctx: dict) -> dict:
    return _lc4_mcp_call("list-projects", {}, ctx.get("workspace", "."))


def _lc4_format(ctx: dict) -> dict:
    w = ctx.get("workspace", ".")
    try:
        r = _cli([_require("likec4"), "format", w])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("likec4.likec4_format", ctx, str(e))


def _lc4_export_png(ctx: dict) -> dict:
    w   = ctx.get("workspace", ".")
    out = ctx.get("output",    "dist")
    fmt = ctx.get("format",    "png")
    try:
        r = _cli([_require("likec4"), "export", fmt, w, "-o", out])
        return {"exit_code": r.returncode, "output_dir": out}
    except Exception as e:
        return _stub_result("likec4.likec4_export_png_jpg", ctx, str(e))


def _lc4_export_drawio(ctx: dict) -> dict:
    w   = ctx.get("workspace", ".")
    out = ctx.get("output",    "dist")
    try:
        r = _cli([_require("likec4"), "export", "drawio", w, "-o", out])
        return {"exit_code": r.returncode, "output_dir": out}
    except Exception as e:
        return _stub_result("likec4.likec4_export_drawio", ctx, str(e))


def _lc4_serve(ctx: dict) -> dict:
    w    = ctx.get("workspace", ".")
    port = ctx.get("port", 61000)
    return {"command": f"likec4 start {w} --port {port}",
            "note": "Long-running process — launch externally or in background thread."}


def _lc4_preview(ctx: dict) -> dict:
    w   = ctx.get("workspace", ".")
    out = ctx.get("output",    "preview")
    try:
        r = _cli([_require("likec4"), "build", "--preview", w, "-o", out])
        return {"exit_code": r.returncode, "output_dir": out}
    except Exception as e:
        return _stub_result("likec4.likec4_preview", ctx, str(e))


def _lc4_list_icons(ctx: dict) -> dict:
    try:
        r = _cli([_require("likec4"), "icons", "--list"])
        return {"icons": r.stdout.splitlines()}
    except Exception as e:
        return _stub_result("likec4.likec4_list_icons", ctx, str(e))


def _lc4_codegen_react(ctx: dict) -> dict:
    w   = ctx.get("workspace", ".")
    out = ctx.get("output", "src/generated")
    try:
        r = _cli([_require("likec4"), "gen", "react", w, "-o", out])
        return {"exit_code": r.returncode, "output_dir": out}
    except Exception as e:
        return _stub_result("likec4.likec4_codegen_react", ctx, str(e))


def _lc4_codegen_wc(ctx: dict) -> dict:
    w   = ctx.get("workspace", ".")
    out = ctx.get("output", "src/generated")
    try:
        r = _cli([_require("likec4"), "gen", "webcomponent", w, "-o", out])
        return {"exit_code": r.returncode, "output_dir": out}
    except Exception as e:
        return _stub_result("likec4.likec4_codegen_webcomponent", ctx, str(e))


def _lc4_open_view(ctx: dict) -> dict:
    return _lc4_mcp_call("open-view",
                         {"viewId": ctx.get("view_id", "")},
                         ctx.get("workspace", "."))


def _lc4_stub(name: str):
    return lambda ctx: _stub_result(f"likec4.{name}", ctx)


def _lc4_query_outgoers(ctx: dict) -> dict:
    return _lc4_mcp_call("query-outgoers-graph",
                         {"elementId": ctx.get("element_id", "")},
                         ctx.get("workspace", "."))


def _lc4_query_by_tag_pattern(ctx: dict) -> dict:
    return _lc4_mcp_call("query-by-tag-pattern",
                         {"pattern": ctx.get("pattern", "")},
                         ctx.get("workspace", "."))


def _lc4_batch_read_elements(ctx: dict) -> dict:
    return _lc4_mcp_call("batch-read-elements",
                         {"elementIds": ctx.get("element_ids", [])},
                         ctx.get("workspace", "."))


def _lc4_find_relationships_direct(ctx: dict) -> dict:
    """find-relationships: ALL direct relations of an element (≠find-relationship-paths)."""
    return _lc4_mcp_call("find-relationships",
                         {"elementId": ctx.get("element_id", "")},
                         ctx.get("workspace", "."))


LIKEC4_HANDLERS = {
    "likec4_build":               _lc4_build,
    "likec4_validate":            _lc4_validate,
    "likec4_format":              _lc4_format,
    "likec4_export_json":         _lc4_export_json,
    "likec4_export_png_jpg":      _lc4_export_png,
    "likec4_export_drawio":       _lc4_export_drawio,
    "likec4_codegen_model":       _lc4_codegen,
    "likec4_codegen_react":       _lc4_codegen_react,
    "likec4_codegen_webcomponent":_lc4_codegen_wc,
    "likec4_sync_leanix":         _lc4_stub("likec4_sync_leanix"),   # external SaaS API key required
    "likec4_serve":               _lc4_serve,
    "likec4_preview":             _lc4_preview,
    "likec4_list_icons":          _lc4_list_icons,
    "likec4_mcp":                 _lc4_mcp_start,
    "query_graph":                _lc4_query_graph,
    "query_incomers_graph":       _lc4_query_incomers,
    "query_by_tags":              _lc4_query_by_tags,
    "query_by_metadata":          _lc4_query_by_metadata,
    "search_element":             _lc4_search_element,
    "read_element":               _lc4_read_element,
    "read_view":                  _lc4_read_view,
    "read_deployment":            _lc4_read_depl,
    "read_project_summary":       _lc4_read_project_summary,
    "subgraph_summary":           _lc4_subgraph_summary,
    "find_relationships":         _lc4_find_rel,
    "element_diff":               _lc4_element_diff,
    "open_view":                  _lc4_open_view,
    "apply_semantic_layout":      _lc4_apply_layout,
    "list_projects":              _lc4_list_projects,
    "query_outgoers_graph":       _lc4_query_outgoers,
    "query_by_tag_pattern":       _lc4_query_by_tag_pattern,
    "batch_read_elements":        _lc4_batch_read_elements,
    "find_relationships":         _lc4_find_relationships_direct,
}

# ══════════════════════════════════════════════════════════════════════════════
#  3. C4INTERFLOW
# ══════════════════════════════════════════════════════════════════════════════

def _c4if_execute(ctx: dict) -> dict:
    try:
        workspace = ctx.get("workspace", ".")
        strategy  = ctx.get("strategy", "default")
        r = _cli([_require("dotnet"), "run", "--project", workspace,
                  "--strategy", strategy])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("c4if.executeaacstrategycommand", ctx, str(e))

def _c4if_cmd(cmd_name: str, extra_args: list = None):
    """Generic C4InterFlow dotnet command runner."""
    def _handler(ctx: dict) -> dict:
        workspace  = ctx.get("workspace",   ".")
        aac_root   = ctx.get("aac_root",    workspace)
        output_dir = ctx.get("output_dir",  "output")
        args = [_require("dotnet"), "run", "--project", workspace,
                "--", cmd_name, "--AaCRootNamespace", aac_root,
                "--OutputPath", output_dir]
        if extra_args:
            args += extra_args
        # Pass any ctx keys as --Key Value flags
        for k, v in ctx.items():
            if k not in ("workspace", "aac_root", "output_dir") and isinstance(v, str):
                args += [f"--{k}", v]
        try:
            r = _cli(args)
            return {"exit_code": r.returncode, "output": r.stdout,
                    "command": cmd_name, "output_dir": output_dir}
        except Exception as e:
            return _stub_result(f"c4if.{cmd_name.lower()}", ctx, str(e))
    return _handler


def _c4if_csv_to_yaml(ctx: dict) -> dict:
    csv_file = ctx.get("csv_file", "catalog.csv")
    out_dir  = ctx.get("output_dir", "aac")
    try:
        r = _cli([_require("dotnet"), "run", "--project", ctx.get("workspace", "."),
                  "--", "CsvToYamlAaCWriter",
                  "--InputPath", csv_file, "--OutputPath", out_dir])
        return {"exit_code": r.returncode, "output_dir": out_dir, "output": r.stdout}
    except Exception as e:
        return _stub_result("c4if.csvtoyamlaacwriter", ctx, str(e))


def _c4if_yaml_to_csv(ctx: dict) -> dict:
    aac_dir  = ctx.get("aac_dir", "aac")
    out_file = ctx.get("output_file", "catalog.csv")
    try:
        r = _cli([_require("dotnet"), "run", "--project", ctx.get("workspace", "."),
                  "--", "YamlToCsvAaCGenerator",
                  "--InputPath", aac_dir, "--OutputPath", out_file])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("c4if.yamltocsvaacgenerator", ctx, str(e))


def _c4if_stub(name: str):
    return lambda ctx: _stub_result(f"c4if.{name}", ctx)


C4IF_HANDLERS = {
    "executeaacstrategycommand":    _c4if_execute,
    "drawdiagramscommand":          _c4if_cmd("DrawDiagramsCommand"),
    "queryuseflowscommand":         _c4if_cmd("QueryUseFlowsCommand"),
    "querybyinputcommand":          _c4if_cmd("QueryByInputCommand"),
    "generatedocumentationcommand": _c4if_cmd("GenerateDocumentationCommand"),
    "publishsitecommand":           _c4if_cmd("PublishSiteCommand"),
    "csvtoyamlaacwriter":           _c4if_csv_to_yaml,
    "yamltocsvaacgenerator":        _c4if_yaml_to_csv,
    "executeviewscommand":          _c4if_cmd("ExecuteViewsCommand"),
}

# ══════════════════════════════════════════════════════════════════════════════
#  4. STRUCTURIZR DSL
# ══════════════════════════════════════════════════════════════════════════════

def _struct_parse(ctx: dict) -> dict:
    """Parse a .dsl workspace file using Structurizr CLI."""
    try:
        dsl  = ctx.get("dsl_file", "workspace.dsl")
        r    = _cli([_require("structurizr-cli"), "validate", dsl])
        return {"valid": r.returncode == 0, "output": r.stdout}
    except Exception as e:
        return _stub_result("struct.workspaceparser", ctx, str(e))

def _struct_export(ctx: dict) -> dict:
    try:
        dsl  = ctx.get("dsl_file", "workspace.dsl")
        fmt  = ctx.get("format", "plantuml")
        r    = _cli([_require("structurizr-cli"), "export", "-workspace", dsl, "-format", fmt])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("struct.externe_structurizr_export_c", ctx, str(e))

def _struct_parse_section(section: str):
    """Extract a specific DSL section via structurizr-cli export + grep."""
    import re as _re
    def _handler(ctx: dict) -> dict:
        dsl = ctx.get("dsl_file", "workspace.dsl")
        try:
            content = Path(dsl).read_text()
            # Extract the named block from DSL
            pattern = rf'{section}\s*\{{([^}}]*(?:\{{[^}}]*\}}[^}}]*)*)\}}'
            matches = _re.findall(pattern, content, _re.IGNORECASE | _re.DOTALL)
            if matches:
                return {section: matches, "count": len(matches), "source": dsl}
            # Fallback: use structurizr-cli export + filter
            r = _cli([_require("structurizr-cli"), "export",
                      "-workspace", dsl, "-format", "json"])
            if r.returncode == 0:
                data = json.loads(r.stdout) if r.stdout.startswith("{") else {}
                return {section: data.get(section, data), "source": "structurizr-cli export"}
            return {"error": f"No '{section}' found in {dsl}"}
        except Exception as e:
            return _stub_result(f"struct.{section}parser", ctx, str(e))
    return _handler


def _struct_stub(name: str):
    return lambda ctx: _stub_result(f"struct.{name}", ctx)


STRUCT_HANDLERS = {
    "workspaceparser":              _struct_parse,
    "modelparser":                  _struct_parse_section("model"),
    "personparser":                 _struct_parse_section("person"),
    "relationshipparser":           _struct_parse_section("relationship"),
    "systemcontextviewparser":      _struct_parse_section("systemContextView"),
    "deploymentenvironmentparser":  _struct_parse_section("deploymentEnvironment"),
    "dynamicviewparser":            _struct_parse_section("dynamicView"),
    "stylesparser":                 _struct_parse_section("styles"),
    "externe_structurizr_export_c": _struct_export,
}

# ══════════════════════════════════════════════════════════════════════════════
#  5. CONTAINERLAB
# ══════════════════════════════════════════════════════════════════════════════

def _clab_generate(ctx: dict) -> dict:
    """Generate a containerlab topology YAML from a deployment model."""
    template = ctx.get("template")
    output   = ctx.get("output", "topology.clab.yml")
    if template:
        try:
            import jinja2
            tpl = jinja2.Template(template)
            rendered = tpl.render(**ctx.get("vars", {}))
            Path(output).write_text(rendered)
            return {"topology_file": output, "content": rendered}
        except ImportError:
            pass
    return _stub_result("clab.clab_generate", ctx, "jinja2 not installed for template render")

def _clab_deploy(ctx: dict) -> dict:
    topo = ctx.get("topology", "topology.clab.yml")
    try:
        r = _cli([_require("containerlab"), "deploy", "-t", topo])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_deploy", ctx, str(e))

def _clab_save(ctx: dict) -> dict:
    topo = ctx.get("topology", "topology.clab.yml")
    try:
        r    = _cli([_require("containerlab"), "save", "-t", topo])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_save", ctx, str(e))

def _clab_inspect(ctx: dict) -> dict:
    topo = ctx.get("topology", "topology.clab.yml")
    try:
        r = _cli([_require("containerlab"), "inspect", "-t", topo, "--format", "json"])
        return json.loads(r.stdout) if r.returncode == 0 else {"raw": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_inspect", ctx, str(e))

def _clab_graph(ctx: dict) -> dict:
    topo = ctx.get("topology", "topology.clab.yml")
    out  = ctx.get("output", "topology.html")
    try:
        r = _cli([_require("containerlab"), "graph", "-t", topo, "--srv", ":0",
                  "--static", out])
        return {"output_file": out, "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("clab.clab_graph", ctx, str(e))

def _clab_stub(name: str):
    return lambda ctx: _stub_result(f"clab.{name}", ctx)


def _clab_destroy(ctx: dict) -> dict:
    topo = ctx.get("topology", "topology.clab.yml")
    cleanup = ctx.get("cleanup", True)
    try:
        cmd = [_require("containerlab"), "destroy", "-t", topo]
        if cleanup:
            cmd.append("--cleanup")
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_destroy", ctx, str(e))


def _clab_redeploy(ctx: dict) -> dict:
    """Destroy + deploy in one call."""
    d = _clab_destroy(ctx)
    if d.get("exit_code", 1) != 0:
        return {"error": "destroy failed", "destroy": d}
    dep = _clab_deploy(ctx)
    return {"destroy": d, "deploy": dep}


def _clab_inspect_interfaces(ctx: dict) -> dict:
    topo = ctx.get("topology", "topology.clab.yml")
    node = ctx.get("node", "")
    try:
        cmd = [_require("containerlab"), "interfaces", "-t", topo, "--format", "json"]
        if node:
            cmd += ["--node", node]
        r = _cli(cmd)
        return json.loads(r.stdout) if r.returncode == 0 else {"raw": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_inspect_interfaces", ctx, str(e))


def _clab_exec(ctx: dict) -> dict:
    topo    = ctx.get("topology", "topology.clab.yml")
    node    = ctx.get("node", "")
    command = ctx.get("command", "ip link show")
    try:
        cmd = [_require("containerlab"), "exec", "-t", topo, "--cmd", command]
        if node:
            cmd += ["--node", node]
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout, "node": node}
    except Exception as e:
        return _stub_result("clab.clab_exec", ctx, str(e))


def _clab_netem(ctx: dict) -> dict:
    """clab tools netem — inject latency/jitter/loss on a link."""
    topo  = ctx.get("topology", "topology.clab.yml")
    node  = ctx.get("node", "")
    iface = ctx.get("interface", "eth1")
    delay = ctx.get("delay", "100ms")
    jitter = ctx.get("jitter", "10ms")
    loss   = ctx.get("loss",  0)
    try:
        cmd = [_require("containerlab"), "tools", "netem",
               "-t", topo, "--node", node, "--interface", iface,
               "--delay", delay, "--jitter", jitter, "--loss", str(loss)]
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout,
                "params": {"delay": delay, "jitter": jitter, "loss": loss}}
    except Exception as e:
        return _stub_result("clab.clab_tools_netem", ctx, str(e))


def _clab_vxlan(ctx: dict) -> dict:
    """clab tools vxlan — create VXLAN tunnel between labs."""
    remote = ctx.get("remote",  "192.168.0.2")
    id_    = ctx.get("id",      100)
    link   = ctx.get("link",    "eth0")
    try:
        cmd = [_require("containerlab"), "tools", "vxlan",
               "--remote", remote, "--id", str(id_), "--link", link]
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_tools_vxlan", ctx, str(e))


def _clab_cert(ctx: dict) -> dict:
    """clab tools cert — generate TLS certificates for lab nodes."""
    ca   = ctx.get("ca",   "clab-ca")
    node = ctx.get("node", "")
    try:
        cmd = [_require("containerlab"), "tools", "cert", "issue",
               "--ca", ca]
        if node:
            cmd += ["--node", node]
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("clab.clab_tools_cert", ctx, str(e))


CLAB_HANDLERS = {
    "clab_generate":           _clab_generate,
    "clab_deploy":             _clab_deploy,
    "clab_destroy":            _clab_destroy,
    "clab_redeploy":           _clab_redeploy,
    "clab_inspect":            _clab_inspect,
    "clab_inspect_interfaces": _clab_inspect_interfaces,
    "clab_graph":              _clab_graph,
    "clab_save":               _clab_save,
    "clab_exec":               _clab_exec,
    "clab_tools_netem":        _clab_netem,
    "clab_tools_vxlan":        _clab_vxlan,
    "clab_tools_cert":         _clab_cert,
}

# ══════════════════════════════════════════════════════════════════════════════
#  6. OPEN POLICY AGENT
# ══════════════════════════════════════════════════════════════════════════════

def _opa_eval(ctx: dict) -> dict:
    query  = ctx.get("query",   "data")
    policy = ctx.get("policy",  "")
    data   = ctx.get("input",   {})
    flags  = []
    if policy:
        flags += ["-d", policy]
    try:
        r = _cli([_require("opa"), "eval", *flags, "-I", "--format", "json", query],
                 input_data=json.dumps(data))
        return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr}
    except Exception as e:
        return _stub_result("opa.opa_eval", ctx, str(e))

def _opa_check(ctx: dict) -> dict:
    files = ctx.get("files", [ctx.get("policy", "policy.rego")])
    try:
        r = _cli([_require("opa"), "check", "--strict"] + files)
        return {"valid": r.returncode == 0, "output": r.stdout + r.stderr}
    except Exception as e:
        return _stub_result("opa.opa_check", ctx, str(e))

def _opa_test(ctx: dict) -> dict:
    files = ctx.get("files", ["."])
    try:
        r = _cli([_require("opa"), "test", "-v"] + files)
        return {"passed": r.returncode == 0, "output": r.stdout}
    except Exception as e:
        return _stub_result("opa.opa_test", ctx, str(e))

def _opa_build(ctx: dict) -> dict:
    src    = ctx.get("src",    ".")
    output = ctx.get("output", "bundle.tar.gz")
    try:
        r = _cli([_require("opa"), "build", src, "-o", output])
        return {"bundle": output, "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("opa.opa_build", ctx, str(e))

def _opa_server(ctx: dict) -> dict:
    addr   = ctx.get("addr",   "0.0.0.0:8181")
    bundle = ctx.get("bundle", ".")
    return _stub_result("opa.opa_run_server",  ctx,
                        f"start: opa run --server -b {bundle} --addr {addr}")

def _opa_fmt(ctx: dict) -> dict:
    files = ctx.get("files", [ctx.get("policy", ".")])
    write = ctx.get("write", True)
    try:
        cmd = [_require("opa"), "fmt"] + (["--write"] if write else []) + files
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("opa.opa_fmt", ctx, str(e))


def _opa_exec(ctx: dict) -> dict:
    """opa exec — batch evaluation over multiple input files (Phase 3 UC-02)."""
    bundle = ctx.get("bundle",  ".")
    inputs = ctx.get("inputs",  ["input.json"])
    query  = ctx.get("query",   "data.nexus.allow")
    try:
        cmd = [_require("opa"), "exec", "--bundle", bundle,
               "--decision", query, "--format", "json"] + inputs
        r = _cli(cmd)
        return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr}
    except Exception as e:
        return _stub_result("opa.opa_exec", ctx, str(e))


def _opa_deps(ctx: dict) -> dict:
    query  = ctx.get("query",  "data.nexus.allow")
    bundle = ctx.get("bundle", ".")
    try:
        r = _cli([_require("opa"), "deps", "--bundle", bundle, query])
        return {"deps": r.stdout.splitlines(), "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("opa.opa_deps", ctx, str(e))


def _opa_inspect(ctx: dict) -> dict:
    path = ctx.get("path", ".")
    try:
        r = _cli([_require("opa"), "inspect", path, "--format", "json"])
        return json.loads(r.stdout) if r.returncode == 0 else {"raw": r.stdout}
    except Exception as e:
        return _stub_result("opa.opa_inspect", ctx, str(e))


def _opa_parse(ctx: dict) -> dict:
    policy = ctx.get("policy", "policy.rego")
    try:
        r = _cli([_require("opa"), "parse", policy, "--format", "json"])
        return json.loads(r.stdout) if r.returncode == 0 else {"raw": r.stdout}
    except Exception as e:
        return _stub_result("opa.opa_parse", ctx, str(e))


def _opa_capabilities(ctx: dict) -> dict:
    version = ctx.get("version", "")
    try:
        cmd = [_require("opa"), "capabilities"]
        if version:
            cmd += ["--version", version]
        r = _cli(cmd)
        return json.loads(r.stdout) if r.returncode == 0 else {"raw": r.stdout}
    except Exception as e:
        return _stub_result("opa.opa_capabilities", ctx, str(e))


def _opa_sign(ctx: dict) -> dict:
    bundle = ctx.get("bundle",     "bundle.tar.gz")
    key    = ctx.get("signing_key","")
    alg    = ctx.get("algorithm",  "RS256")
    try:
        cmd = [_require("opa"), "sign", "--bundle", bundle,
               "--signing-alg", alg]
        if key:
            cmd += ["--signing-key", key]
        r = _cli(cmd)
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("opa.opa_sign", ctx, str(e))


def _opa_stub(name: str):
    return lambda ctx: _stub_result(f"opa.{name}", ctx)


OPA_HANDLERS = {
    "opa_eval":         _opa_eval,
    "opa_check":        _opa_check,
    "opa_test":         _opa_test,
    "opa_fmt":          _opa_fmt,
    "opa_build":        _opa_build,
    "opa_sign":         _opa_sign,
    "opa_run_server":   _opa_server,
    "opa_deps":         _opa_deps,
    "opa_inspect":      _opa_inspect,
    "opa_parse":        _opa_parse,
    "opa_capabilities": _opa_capabilities,
    "opa_exec":         _opa_exec,
}

# ══════════════════════════════════════════════════════════════════════════════
#  7. BATFISH
# ══════════════════════════════════════════════════════════════════════════════

def _bf_init_session(ctx: dict):
    try:
        from pybatfish.client.session import Session
        host    = ctx.get("host",     "localhost")
        network = ctx.get("network",  "nexus-net")
        snap    = ctx.get("snapshot", "snap1")
        snap_dir = ctx.get("snapshot_dir", ".")
        bf = Session(host=host)
        bf.set_network(network)
        bf.init_snapshot(snap_dir, name=snap, overwrite=True)
        return bf
    except ImportError:
        return None

def _bf_question(name: str):
    def _handler(ctx: dict) -> dict:
        bf = _bf_init_session(ctx)
        if bf is None:
            return _stub_result(f"bf.{name}", ctx, "pybatfish not installed")
        try:
            import pybatfish.question.question as bfq
            q_fn = getattr(bfq, name.replace("bfq_", ""), None)
            if q_fn is None:
                raise AttributeError(f"pybatfish has no question {name}")
            df = q_fn().answer().frame()
            return {"rows": df.to_dict(orient="records"), "columns": list(df.columns)}
        except Exception as e:
            return _stub_result(f"bf.{name}", ctx, str(e))
    return _handler

BF_HANDLERS = {
    "bfq_testfilters":           _bf_question("bfq_testfilters"),
    "bfq_routes":                _bf_question("bfq_routes"),
    "bfq_bgpedges":              _bf_question("bfq_bgpedges"),
    "bfq_undefinedreferences":   _bf_question("bfq_undefinedreferences"),
    "bfq_unusedstructures":      _bf_question("bfq_unusedstructures"),
    "bfq_initissues":            _bf_question("bfq_initissues"),
    "bfq_ipowners":              _bf_question("bfq_ipowners"),
    "bfq_aaaauthenticationlogin":_bf_question("bfq_aaaauthenticationlogin"),
    "bfq_ipsecsessionstatus":    _bf_question("bfq_ipsecsessionstatus"),
    "bfq_vxlanedges":            _bf_question("bfq_vxlanedges"),
}

# ══════════════════════════════════════════════════════════════════════════════
#  8. OWASP THREAT DRAGON
# ══════════════════════════════════════════════════════════════════════════════

def _td_create(ctx: dict) -> dict:
    """Create a new Threat Dragon model via REST API."""
    try:
        import requests
        base = ctx.get("base_url", "http://localhost:3000")
        payload = {
            "summary": {"title": ctx.get("title", "New model"), "owner": ctx.get("owner", "")},
            "detail":  {"diagrams": [], "contributors": []}
        }
        r = requests.post(f"{base}/api/threatmodel", json=payload,
                          headers={"Authorization": f"Bearer {ctx.get('token','')}"})
        return r.json()
    except Exception as e:
        return _stub_result("td.threatmodelcontroller_create", ctx, str(e))

def _td_api(ctx: dict, method: str, path: str, body: dict = None) -> dict:
    """Generic Threat Dragon REST API call."""
    try:
        import requests
        base    = ctx.get("base_url", "http://localhost:3000")
        token   = ctx.get("token", "")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{base}{path}"
        fn  = getattr(requests, method.lower())
        r   = fn(url, headers=headers, json=body, timeout=10)
        try:
            return r.json()
        except Exception:
            return {"status_code": r.status_code, "text": r.text[:500]}
    except ImportError:
        return _stub_result("td.api", ctx, "requests not installed")
    except Exception as e:
        return _stub_result("td.api", ctx, str(e))


def _td_update(ctx: dict) -> dict:
    model_id = ctx.get("model_id", "")
    model    = ctx.get("model",    {})
    return _td_api(ctx, "PUT", f"/api/threatmodel/{model_id}", model)


def _td_get(ctx: dict) -> dict:
    model_id = ctx.get("model_id", "")
    if model_id:
        return _td_api(ctx, "GET", f"/api/threatmodel/{model_id}")
    return _td_api(ctx, "GET", "/api/threatmodel")


def _td_delete(ctx: dict) -> dict:
    model_id = ctx.get("model_id", "")
    return _td_api(ctx, "DELETE", f"/api/threatmodel/{model_id}")


def _td_repos(ctx: dict) -> dict:
    provider = ctx.get("provider", "github")     # github | gitlab | bitbucket
    return _td_api(ctx, "GET", f"/api/repos/{provider}")


def _td_x6_dfd(ctx: dict) -> dict:
    """Build a DFD payload for the X6.js canvas (exclusive to Threat Dragon)."""
    elements = ctx.get("elements", [])
    flows    = ctx.get("flows",    [])
    boundary = ctx.get("boundaries", [])
    diagram = {
        "diagramType": "STRIDE",
        "cells": [],
    }
    for el in elements:
        diagram["cells"].append({
            "type":  el.get("type", "tm.Process"),
            "label": el.get("name", ""),
            "data":  el,
        })
    for fl in flows:
        diagram["cells"].append({
            "type":   "tm.Flow",
            "source": {"id": fl.get("from")},
            "target": {"id": fl.get("to")},
            "label":  fl.get("name", ""),
            "data":   fl,
        })
    for b in boundary:
        diagram["cells"].append({"type": "tm.Boundary", "label": b.get("name", "")})
    return {"diagram": diagram,
            "note": "POST to /api/threatmodel/<id> to load in X6.js editor"}


def _td_methodology(method: str):
    """IMPORTANT: stride.js / linddun.js / cia.js / ciadie.js / plot4ai.js /
    cornucopia.js are Vue.js FRONTEND modules running in-browser via X6.js.
    There is NO server-side REST endpoint for threat generation.
    These handlers document the client-side module interface and
    the model type to pass when creating/updating a diagram via the REST API.
    """
    FRONTEND_MODULES = {
        "STRIDE":     "td.vue/src/service/threats/models/stride.js",
        "LINDDUN":    "td.vue/src/service/threats/models/linddun.js",
        "CIA":        "td.vue/src/service/threats/models/cia.js",
        "CIADIE":     "td.vue/src/service/threats/models/ciadie.js",
        "PLOT4ai":    "td.vue/src/service/threats/models/plot4ai.js",
        "Cornucopia": "td.vue/src/service/threats/models/eop/cornucopia.js",
    }
    def _handler(ctx: dict) -> dict:
        diagram_type = method.upper()
        model_id     = ctx.get("model_id", "")
        model_data   = ctx.get("model_data", {})
        # The way to activate a methodology in TD is to set diagramType
        # in the threat model JSON, then save via REST API.
        # Threat generation itself happens client-side in X6.js editor.
        if model_id and model_data:
            model_data.setdefault("diagramType", diagram_type)
            return _td_api(ctx, "PUT",
                f"/api/threatmodel/{ctx.get('org','org')}/{ctx.get('repo','repo')}"
                f"/{ctx.get('branch','main')}/{model_id}/update",
                model_data)
        return {
            "methodology": method,
            "diagramType_value": diagram_type,
            "frontend_module": FRONTEND_MODULES.get(method, ""),
            "note": (
                f"Set diagramType='{diagram_type}' in your TD model JSON, "
                "then save via PUT /api/threatmodel/.../update. "
                "Threat generation for this methodology runs client-side "
                "in the X6.js editor (Vue.js). "
                "See getThreatTypesByElement() in threats/models/index.js."
            ),
            "supported_cell_types": ["tm.Actor", "tm.Process", "tm.Store", "tm.Flow"],
        }
    return _handler


def _td_oats(ctx: dict) -> dict:
    """GetContextSuggestions() is a client-side JS function in
    oats/context-generator.js — no server REST endpoint exists.
    This handler provides the model data needed to feed the frontend function.
    """
    model_id = ctx.get("model_id", "")
    if model_id:
        # Fetch the model data which the frontend context-generator will consume
        return _td_api(ctx, "GET",
            f"/api/threatmodel/{ctx.get('org','org')}/{ctx.get('repo','repo')}"
            f"/{ctx.get('branch','main')}/{model_id}/data")
    return {
        "note": "GetContextSuggestions(element, model) is a Vue.js frontend function. "
                "Fetch the model via GET /api/threatmodel/.../data, "
                "then pass elements to the JS function in-browser.",
        "frontend_source": "td.vue/src/service/threats/oats/context-generator.js",
    }


def _td_tmbom(ctx: dict) -> dict:
    """TM-BOM migration is client-side JS (tmBom.js).
    No server REST endpoint — migration runs in the browser.
    This handler documents the migration module location.
    """
    return {
        "note": "TM-BOM migration runs client-side via td.vue/src/service/migration/tmBom/tmBom.js. "
                "Load the legacy file in the Threat Dragon UI to trigger migration automatically.",
        "frontend_source": "td.vue/src/service/migration/tmBom/",
        "td_v1_migration": "td.vue/src/service/migration/tdV1/threatDragonV1.js",
    }


def _td_stub(name: str):
    return lambda ctx: _stub_result(f"td.{name}", ctx)


TD_HANDLERS = {
    "threatmodelcontroller_create":  _td_create,
    "threatmodelcontroller_update":  _td_update,
    "threatmodelcontroller_model":   _td_get,
    "threatmodelcontroller_delete":  _td_delete,
    "threatmodelcontroller_repos":   _td_repos,
    "editeur_de_diagramme_x6_form":  _td_x6_dfd,
    "stride_js":                     _td_methodology("STRIDE"),
    "linddun_js":                    _td_methodology("LINDDUN"),
    "cia_js":                        _td_methodology("CIA"),
    "plot4ai_js":                    _td_methodology("PLOT4ai"),
    "cornucopia_js":                 _td_methodology("Cornucopia"),
    "context_generator_js_oats":     _td_oats,
    "tmbom_js_migration":            _td_tmbom,
}



# ══════════════════════════════════════════════════════════════════════════════
#  9. OWASP PYTM
# ══════════════════════════════════════════════════════════════════════════════

def _pytm_process(ctx: dict) -> dict:
    try:
        script = ctx.get("script")
        if script and Path(script).exists():
            r = _cli(["python", script])
            return {"exit_code": r.returncode, "output": r.stdout}
        import pytm
        from pytm import TM, Server, Datastore, Dataflow, Boundary, Actor
        tm = TM(ctx.get("name", "Threat Model"), description=ctx.get("description", ""))
        return {"tm_name": tm.name, "status": "initialized"}
    except Exception as e:
        return _stub_result("pytm.tm_process", ctx, str(e))

def _pytm_resolve(ctx: dict) -> dict:
    """Run tm.process() which resolves all 114 CAPEC threats against model elements.

    Methodologies auto-resolved: STRIDE, CIA, LINDDUN, PLOT4ai, CIADIE, EOP.
    """
    try:
        script = ctx.get("script")
        if script and Path(script).exists():
            # Run with --json to capture resolved threats
            out_file = ctx.get("json_output", "threat_model.json")
            r = _cli(["python", script, "--json", out_file])
            if r.returncode == 0:
                try:
                    import os
                    findings = json.loads(open(out_file).read()) if os.path.exists(out_file) else json.loads(r.stdout)
                    return {"resolved": findings, "methodologies": [
                        "STRIDE", "CIA", "CIADIE", "LINDDUN", "PLOT4ai", "EOP"
                    ]}
                except json.JSONDecodeError:
                    return {"output": r.stdout, "methodologies": [
                        "STRIDE", "CIA", "CIADIE", "LINDDUN", "PLOT4ai", "EOP"
                    ]}
            raise RuntimeError(r.stderr)
        import pytm as _pytm_mod
        return _stub_result("pytm.tm_resolve", ctx,
                            "pass 'script' key with path to your tm.py")
    except Exception as e:
        return _stub_result("pytm.tm_resolve", ctx, str(e))

def _pytm_report(ctx: dict) -> dict:
    try:
        script = ctx.get("script")
        out    = ctx.get("output", "report.html")
        if script:
            r = _cli(["python", script, "--report", out])
            return {"report_file": out, "exit_code": r.returncode}
        return _stub_result("pytm.tm_report", ctx, "no script provided")
    except Exception as e:
        return _stub_result("pytm.tm_report", ctx, str(e))

def _pytm_json(ctx: dict) -> dict:
    try:
        script = ctx.get("script")
        if script:
            r = _cli(["python", script, "--json"])
            return json.loads(r.stdout)
        return _stub_result("pytm.json", ctx, "no script provided")
    except Exception as e:
        return _stub_result("pytm.json", ctx, str(e))

def _pytm_check(ctx: dict) -> dict:
    """TM.check() — validates boundary crossings and model consistency."""
    try:
        script = ctx.get("script")
        if script and Path(script).exists():
            r = _cli(["python", script, "--check"])
            return {"valid": r.returncode == 0, "issues": r.stdout.splitlines()}
        return _stub_result("pytm.tm_check", ctx, "no script provided")
    except Exception as e:
        return _stub_result("pytm.tm_check", ctx, str(e))


def _pytm_dfd(ctx: dict) -> dict:
    """TM.dfd() — generates Data Flow Diagram via Graphviz (dot → PNG/SVG)."""
    try:
        script = ctx.get("script")
        fmt    = ctx.get("fmt", "png")
        out    = ctx.get("output", f"dfd.{fmt}")
        if script and Path(script).exists():
            r = _cli(["python", script, "--dfd"])
            if r.returncode == 0:
                dot_src = r.stdout
                if shutil.which("dot"):
                    r2 = _cli(["dot", f"-T{fmt}", "-o", out], input_data=dot_src)
                    return {"dfd_file": out, "exit_code": r2.returncode, "format": fmt}
                Path(out.replace(f".{fmt}", ".dot")).write_text(dot_src)
                return {"dot_file": out.replace(f".{fmt}", ".dot"),
                        "warning": "graphviz 'dot' not found — wrote .dot only"}
            raise RuntimeError(r.stderr)
        return _stub_result("pytm.tm_dfd", ctx, "no script provided")
    except Exception as e:
        return _stub_result("pytm.tm_dfd", ctx, str(e))


def _pytm_seq(ctx: dict) -> dict:
    """TM.seq() — generates sequence diagram (PlantUML .puml)."""
    try:
        script = ctx.get("script")
        out    = ctx.get("output", "sequence.puml")
        if script and Path(script).exists():
            r = _cli(["python", script, "--seq"])
            if r.returncode == 0:
                Path(out).write_text(r.stdout)
                return {"puml_file": out, "lines": len(r.stdout.splitlines())}
            raise RuntimeError(r.stderr)
        return _stub_result("pytm.tm_seq", ctx, "no script provided")
    except Exception as e:
        return _stub_result("pytm.tm_seq", ctx, str(e))


def _pytm_list(ctx: dict) -> dict:
    """--list — lists all threats in the threatlib (114 CAPEC entries)."""
    try:
        r = _cli(["python", "-m", "pytm", "--list"])
        if r.returncode == 0:
            threats = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
            return {"threats": threats, "count": len(threats)}
        raise RuntimeError(r.stderr)
    except Exception as e:
        return _stub_result("pytm.list", ctx, str(e))


def _pytm_describe(ctx: dict) -> dict:
    """--describe <ElementType> — introspects available properties."""
    try:
        element_type = ctx.get("element_type", "Server")
        r = _cli(["python", "-m", "pytm", "--describe", element_type])
        if r.returncode == 0:
            return {"element_type": element_type, "properties": r.stdout}
        raise RuntimeError(r.stderr)
    except Exception as e:
        return _stub_result("pytm.describe", ctx, str(e))


def _pytm_stale(ctx: dict) -> dict:
    """_stale() / --stale_days N — detects model drift vs code timestamps."""
    try:
        script     = ctx.get("script")
        stale_days = int(ctx.get("stale_days", 30))
        if script and Path(script).exists():
            r = _cli(["python", script, "--stale_days", str(stale_days)])
            lines = r.stdout.splitlines()
            stale = any("stale" in ln.lower() or "drift" in ln.lower() for ln in lines)
            return {
                "stale": stale,
                "delta_days_threshold": stale_days,
                "output": r.stdout,
                "exit_code": r.returncode,
            }
        return _stub_result("pytm.stale", ctx, "no script provided — pass 'script' key")
    except Exception as e:
        return _stub_result("pytm.stale", ctx, str(e))


def _pytm_llm_threats(ctx: dict) -> dict:
    """Filter the 8 LLM-specific threats from a resolved pytm JSON output.

    The 8 threats target: LLM elements (Server/Process with technology=LLM).
      1. Prompt Injection          (CAPEC-126)
      2. Model Inversion Attack    (CAPEC-112)
      3. Data Poisoning            (CAPEC-33)
      4. Adversarial Input         (CAPEC-154)
      5. Model Extraction/Theft    (CAPEC-191)
      6. Insecure Output Handling  (CWE-116)
      7. Excessive Agency          (OWASP LLM-08)
      8. Insecure Plugin Design    (OWASP LLM-07)
    """
    try:
        resolved = ctx.get("resolved", {})
        findings = resolved.get("findings", []) if isinstance(resolved, dict) else []

        LLM_THREAT_NAMES = {
            "prompt injection", "model inversion", "data poisoning",
            "adversarial input", "model extraction", "insecure output",
            "excessive agency", "insecure plugin",
        }

        llm_findings = [
            f for f in findings
            if any(kw in f.get("description", "").lower() or
                   kw in f.get("name", "").lower()
                   for kw in LLM_THREAT_NAMES)
        ]

        return {
            "llm_findings": llm_findings,
            "count": len(llm_findings),
            "target": "LLM",
            "note": "8 LLM threats from pytm threatlib (target: LLM). "
                    "Requires element technology='LLM' to trigger."
        }
    except Exception as e:
        return _stub_result("pytm.llm_threats", ctx, str(e))


def _pytm_ci(ctx: dict) -> dict:
    """CI pipeline integration: python tm.py --json with exit-code on critical findings.

    Usage in pipeline:
        python tm.py --json > threat_model.json
        python tm.py --stale_days 30   # fails if model is stale
    """
    try:
        script     = ctx.get("script")
        stale_days = ctx.get("stale_days", 30)
        fail_on    = ctx.get("fail_on_severity", "HIGH")

        if not script or not Path(script).exists():
            return _stub_result("pytm.ci_pipeline", ctx, "no script provided")

        results = {}

        # Step 1: export JSON
        json_out = ctx.get("json_output", "threat_model.json")
        r_json = _cli(["python", script, "--json", json_out])
        if r_json.returncode == 0:
            try:
                import os
                findings = json.loads(open(json_out).read()) if os.path.exists(json_out) else json.loads(r_json.stdout)
                results["findings"] = findings
                results["json_ok"] = True
            except json.JSONDecodeError:
                results["json_ok"] = False
                results["raw_output"] = r_json.stdout

        # Step 2: staleness check
        r_stale = _cli(["python", script, "--stale_days", str(stale_days)])
        results["stale_check"] = {
            "exit_code": r_stale.returncode,
            "stale": r_stale.returncode != 0,
            "threshold_days": stale_days,
        }

        # Step 3: determine CI exit code
        high_severity = [
            f for f in (results.get("findings") or {}).get("findings", [])
            if f.get("severity", "").upper() == fail_on.upper()
        ]
        results["ci_pass"]   = len(high_severity) == 0 and not results["stale_check"]["stale"]
        results["exit_code"] = 0 if results["ci_pass"] else 1
        results["fail_on"]   = fail_on

        return results

    except Exception as e:
        return _stub_result("pytm.ci_pipeline", ctx, str(e))


def _pytm_versioning(ctx: dict) -> dict:
    """tm.py is the model — git-native versioning: diff, blame, PR on threat changes."""
    try:
        script = ctx.get("script", "tm.py")
        if not shutil.which("git"):
            return _stub_result("pytm.versioning", ctx, "git not in PATH")
        r = _cli(["git", "log", "--oneline", "-10", "--", script])
        commits = r.stdout.strip().splitlines()
        return {"last_10_commits": commits, "script": script,
                "note": "pytm model IS Python code — diff/blame/PR on tm.py = threat history"}
    except Exception as e:
        return _stub_result("pytm.versioning", ctx, str(e))


def _pytm_stub(name: str):
    return lambda ctx: _stub_result(f"pytm.{name}", ctx)

PYTM_HANDLERS = {
    "tm_process":   _pytm_process,
    "tm_resolve":   _pytm_resolve,
    "tm_check":     _pytm_check,
    "tm_dfd":       _pytm_dfd,
    "tm_seq":       _pytm_seq,
    "tm_report":    _pytm_report,
    "json":         _pytm_json,
    "list":         _pytm_list,
    "describe":     _pytm_describe,
    "stale":        _pytm_stale,
    "llm_threats":  _pytm_llm_threats,
    "ci_pipeline":  _pytm_ci,
    "versioning":   _pytm_versioning,
}

# ══════════════════════════════════════════════════════════════════════════════
#  10. NEO4J
# ══════════════════════════════════════════════════════════════════════════════

def _neo4j_driver(ctx: dict):
    try:
        from neo4j import GraphDatabase
        uri  = ctx.get("uri",      "bolt://localhost:7687")
        user = ctx.get("user",     "neo4j")
        pwd  = ctx.get("password", os.environ.get("NEO4J_PASSWORD", ""))
        return GraphDatabase.driver(uri, auth=(user, pwd))
    except ImportError:
        return None

def _neo4j_create(ctx: dict) -> dict:
    driver = _neo4j_driver(ctx)
    if not driver:
        return _stub_result("neo4j.create", ctx, "neo4j driver not installed")
    nodes_data = ctx.get("nodes", [])
    rels_data  = ctx.get("relationships", [])
    try:
        with driver.session() as s:
            for nd in nodes_data:
                lbl   = nd.get("label", "Node")
                props = {k: v for k, v in nd.items() if k != "label"}
                s.run(f"MERGE (n:{lbl} {{id: $id}}) SET n += $props",
                      id=nd.get("id", ""), props=props)
            for rd in rels_data:
                rtype = rd.get("type", "RELATES_TO")
                s.run(f"MATCH (a {{id: $src}}), (b {{id: $tgt}}) "
                      f"MERGE (a)-[:{rtype}]->(b)",
                      src=rd["source"], tgt=rd["target"])
        driver.close()
        return {"created_nodes": len(nodes_data), "created_rels": len(rels_data)}
    except Exception as e:
        return _stub_result("neo4j.create", ctx, str(e))

def _neo4j_match(ctx: dict) -> dict:
    driver = _neo4j_driver(ctx)
    if not driver:
        return _stub_result("neo4j.match_return", ctx, "driver not installed")
    cypher = ctx.get("cypher", "MATCH (n) RETURN n LIMIT 25")
    params = ctx.get("params", {})
    try:
        with driver.session() as s:
            result = s.run(cypher, **params)
            rows   = [dict(record) for record in result]
        driver.close()
        return {"rows": rows, "count": len(rows)}
    except Exception as e:
        return _stub_result("neo4j.match_return", ctx, str(e))

def _neo4j_match_path(ctx: dict) -> dict:
    ctx = dict(ctx, cypher=ctx.get("cypher",
        "MATCH p=(a)-[*..5]->(b) WHERE a.id=$src AND b.id=$tgt RETURN p LIMIT 10"))
    return _neo4j_match(ctx)

def _neo4j_set(ctx: dict) -> dict:
    driver = _neo4j_driver(ctx)
    if not driver:
        return _stub_result("neo4j.set", ctx, "driver not installed")
    cypher = ctx.get("cypher", "")
    params = ctx.get("params", {})
    try:
        with driver.session() as s:
            s.run(cypher, **params)
        driver.close()
        return {"ok": True}
    except Exception as e:
        return _stub_result("neo4j.set", ctx, str(e))

def _neo4j_schema(ctx: dict) -> dict:
    ctx2 = dict(ctx, cypher="CALL db.schema.visualization()")
    return _neo4j_match(ctx2)

def _neo4j_node_type_props(ctx: dict) -> dict:
    """db.schema.nodeTypeProperties() — list properties per node/rel type."""
    with _neo4j_driver(ctx) as drv:
        with drv.session() as s:
            result = s.run("CALL db.schema.nodeTypeProperties()")
            return {"nodeTypeProperties": [dict(r) for r in result]}


def _neo4j_labels(ctx: dict) -> dict:
    """db.labels() / db.relationshipTypes() / db.propertyKeys()."""
    with _neo4j_driver(ctx) as drv:
        with drv.session() as s:
            labels = [r["label"] for r in s.run("CALL db.labels()")]
            rel_types = [r["relationshipType"] for r in s.run("CALL db.relationshipTypes()")]
            prop_keys = [r["propertyKey"] for r in s.run("CALL db.propertyKeys()")]
            return {"labels": labels, "relationshipTypes": rel_types, "propertyKeys": prop_keys}


def _neo4j_constraints(ctx: dict) -> dict:
    """CREATE CONSTRAINT / CREATE INDEX for uniqueness or performance."""
    label    = ctx.get("label",    "Node")
    prop     = ctx.get("property", "id")
    name     = ctx.get("name",     f"constraint_{label}_{prop}")
    idx_type = ctx.get("type",     "uniqueness")   # uniqueness | index
    with _neo4j_driver(ctx) as drv:
        with drv.session() as s:
            if idx_type == "uniqueness":
                s.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS "
                      f"FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE")
            else:
                s.run(f"CREATE INDEX {name} IF NOT EXISTS "
                      f"FOR (n:{label}) ON (n.{prop})")
            return {"created": name, "type": idx_type, "label": label, "property": prop}


def _neo4j_listconfig(ctx: dict) -> dict:
    """CALL dbms.listConfig() — list runtime Neo4j configuration."""
    prefix = ctx.get("prefix", "")
    with _neo4j_driver(ctx) as drv:
        with drv.session() as s:
            cypher = "CALL dbms.listConfig()"
            if prefix:
                cypher += f" YIELD name, value WHERE name STARTS WITH '{prefix}'"
            result = s.run(cypher)
            return {"config": [dict(r) for r in result]}


def _neo4j_stub(name: str):
    return lambda ctx: _stub_result(f"neo4j.{name}", ctx)


NEO4J_HANDLERS = {
    "create":                        _neo4j_create,
    "match_return":                  _neo4j_match,
    "match_where_chemin_variable":   _neo4j_match_path,
    "set":                           _neo4j_set,
    "db_schema_visualization":       _neo4j_schema,
    "db_schema_nodetypeproperties":  _neo4j_node_type_props,
    "db_labels":                     _neo4j_labels,
    "contraintes_index_create_con":  _neo4j_constraints,
    "dbms_listconfig":               _neo4j_listconfig,
}

# ══════════════════════════════════════════════════════════════════════════════
#  11. TMDD
# ══════════════════════════════════════════════════════════════════════════════

def _tmdd_init(ctx: dict) -> dict:
    try:
        r = _cli([_require("tmdd"), "init", ctx.get("feature", "feature")])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("tmdd.tmdd_init", ctx, str(e))

def _tmdd_feature(ctx: dict) -> dict:
    try:
        feat = ctx.get("feature", "feature")
        r    = _cli([_require("tmdd"), "feature", feat])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("tmdd.tmdd_feature", ctx, str(e))

def _tmdd_lint(ctx: dict) -> dict:
    try:
        r = _cli([_require("tmdd"), "lint"])
        return {"valid": r.returncode == 0, "output": r.stdout}
    except Exception as e:
        return _stub_result("tmdd.tmdd_lint", ctx, str(e))

def _tmdd_compile(ctx: dict) -> dict:
    try:
        r = _cli([_require("tmdd"), "compile"])
        return {"exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("tmdd.tmdd_compile", ctx, str(e))

def _tmdd_prompt(ctx: dict) -> dict:
    """generate_agent_prompt() — Python API (not a CLI subcommand).
    Called internally by `tmdd compile` / `tmdd feature`. Signature:
        generate_agent_prompt(tm, output_path, feature_name=None) -> str
    """
    model_dir = ctx.get("model_dir", ".tmdd")
    output    = ctx.get("output", "agent_prompt.txt")
    feature   = ctx.get("feature_name")
    try:
        import sys as _sys, importlib
        _sys.path.insert(0, str(Path(model_dir).parent))
        gen_mod  = importlib.import_module("src.generators.agent_prompt")
        util_mod = importlib.import_module("src.utils")
        tm = util_mod.load_threat_model(model_dir)
        content = gen_mod.generate_agent_prompt(tm, output, feature_name=feature)
        return {"prompt_file": output, "length": len(content), "feature": feature}
    except (ImportError, ModuleNotFoundError):
        # Fallback: tmdd compile invokes generate_agent_prompt internally
        try:
            args = [_require("tmdd"), "compile", model_dir]
            if feature:
                args += ["--feature", feature]
            r = _cli(args)
            if Path(output).exists():
                return {"prompt_file": output, "length": Path(output).stat().st_size}
            return {"exit_code": r.returncode, "output": r.stdout}
        except Exception as e2:
            return _stub_result("tmdd.generate_agent_prompt", ctx, str(e2))
    except Exception as e:
        return _stub_result("tmdd.generate_agent_prompt", ctx, str(e))


def _tmdd_threat_prompt(ctx: dict) -> dict:
    """generate_threat_model_prompt() — Python API (not a CLI subcommand).
    Called internally by `tmdd feature`. Signature:
        generate_threat_model_prompt(tm, feature_name, feature_description, model_dir) -> str
    """
    model_dir = ctx.get("model_dir", ".tmdd")
    feat_name = ctx.get("feature_name", "new_feature")
    feat_desc = ctx.get("feature_description", "")
    output    = ctx.get("output", "threat_model_prompt.txt")
    try:
        import sys as _sys, importlib
        _sys.path.insert(0, str(Path(model_dir).parent))
        gen_mod  = importlib.import_module("src.generators.threat_prompt")
        util_mod = importlib.import_module("src.utils")
        tm = util_mod.load_threat_model(model_dir)
        content = gen_mod.generate_threat_model_prompt(tm, feat_name, feat_desc, model_dir)
        Path(output).write_text(content, encoding="utf-8")
        return {"prompt_file": output, "length": len(content)}
    except (ImportError, ModuleNotFoundError):
        # Fallback: tmdd feature creates threat_model_prompt.txt internally
        try:
            r = _cli([_require("tmdd"), "feature", feat_name])
            return {"exit_code": r.returncode, "output": r.stdout}
        except Exception as e2:
            return _stub_result("tmdd.generate_threat_model_prompt", ctx, str(e2))
    except Exception as e:
        return _stub_result("tmdd.generate_threat_model_prompt", ctx, str(e))

def _tmdd_diagram(ctx: dict) -> dict:
    """Generate an interactive HTML threat model diagram (D3/Mermaid)."""
    model_file = ctx.get("model_file", "threat_model.json")
    out        = ctx.get("output",     "threat_diagram.html")
    try:
        r = _cli([_require("tmdd"), "generate", "diagram",
                  "--input", model_file, "--output", out])
        if r.returncode == 0 and Path(out).exists():
            return {"diagram_file": out, "size_bytes": Path(out).stat().st_size}
        # Fallback: generate a minimal Mermaid-based HTML
        try:
            model = json.loads(Path(model_file).read_text())
        except Exception:
            model = {}
        features = model.get("features", [])
        mermaid_nodes = "\n    ".join(
            f"{i}[{f.get('name','?')}]" for i, f in enumerate(features[:20])
        )
        html = f"""<!DOCTYPE html><html><body>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<div class="mermaid">graph TD
    {mermaid_nodes}
</div>
<script>mermaid.initialize({{startOnLoad:true}});</script>
</body></html>"""
        Path(out).write_text(html)
        return {"diagram_file": out, "format": "mermaid-html", "features": len(features)}
    except Exception as e:
        return _stub_result("tmdd.generate_diagram", ctx, str(e))


def _tmdd_report(ctx: dict) -> dict:
    """Generate an HTML/MD threat model report from TMDD output."""
    model_file = ctx.get("model_file", "threat_model.json")
    fmt        = ctx.get("format",     "html")
    out        = ctx.get("output",     f"threat_report.{fmt}")
    try:
        r = _cli([_require("tmdd"), "generate", "report",
                  "--input", model_file, "--format", fmt, "--output", out])
        if r.returncode == 0:
            return {"report_file": out}
        # Fallback: structured MD report
        try:
            model = json.loads(Path(model_file).read_text())
        except Exception:
            model = {}
        lines = ["# TMDD Threat Model Report\n"]
        for feat in model.get("features", []):
            lines.append(f"## {feat.get('name','Feature')}")
            for threat in feat.get("threats", []):
                lines.append(f"- **{threat.get('id','')}** {threat.get('description','')}")
        md = "\n".join(lines)
        out_md = out if fmt == "md" else out.replace(".html", ".md")
        Path(out_md).write_text(md)
        return {"report_file": out_md, "format": "markdown-fallback"}
    except Exception as e:
        return _stub_result("tmdd.generate_report", ctx, str(e))


def _tmdd_stub(name: str):
    return lambda ctx: _stub_result(f"tmdd.{name}", ctx)


TMDD_HANDLERS = {
    "tmdd_init":                    _tmdd_init,
    "tmdd_feature":                 _tmdd_feature,
    "tmdd_lint":                    _tmdd_lint,
    "tmdd_compile":                 _tmdd_compile,
    "generate_threat_model_prompt": _tmdd_threat_prompt,
    "generate_agent_prompt":        _tmdd_prompt,
    "generate_diagram":             _tmdd_diagram,
    "generate_report":              _tmdd_report,
}

# ══════════════════════════════════════════════════════════════════════════════
#  12. SEMGREP
# ══════════════════════════════════════════════════════════════════════════════

def _sg_scan(ctx: dict) -> dict:
    target = ctx.get("target_path", ".")
    config = ctx.get("config",      "auto")
    extra  = ctx.get("extra_flags", [])
    try:
        r = _cli([_require("semgrep"), "scan", "--json",
                  "--config", config, *extra, target])
        return json.loads(r.stdout) if r.returncode in (0, 1) else {"error": r.stderr}
    except Exception as e:
        return _stub_result("semgrep.semgrep_scan", ctx, str(e))

def _sg_scan_custom(ctx: dict) -> dict:
    ctx2 = dict(ctx, config=ctx.get("rule_file", "rules/"), extra_flags=["--sarif"])
    return _sg_scan(ctx2)

def _sg_sca(ctx: dict) -> dict:
    target = ctx.get("target_path", ".")
    try:
        r = _cli([_require("semgrep"), "scan", "--json", "--supply-chain", target])
        return json.loads(r.stdout) if r.returncode in (0, 1) else {"error": r.stderr}
    except Exception as e:
        return _stub_result("semgrep.semgrep_scan_sca", ctx, str(e))

def _sg_write_rule(ctx: dict) -> dict:
    """Build a Semgrep YAML rule from a threat description or AST pattern."""
    threat  = ctx.get("threat", {})
    pattern = ctx.get("pattern", "")
    lang    = ctx.get("language", "python")
    rule_id = ctx.get("rule_id", f"nexus-threat-{threat.get('id','custom')}")
    rule = {
        "rules": [{
            "id":       rule_id,
            "patterns": [{"pattern": pattern}] if pattern else [],
            "message":  threat.get("description", "Security threat detected"),
            "languages":[lang],
            "severity": threat.get("severity", "WARNING"),
            "metadata": {"source": "nexus_compose/tmdd", "threat": threat},
        }]
    }
    out = ctx.get("output", f"{rule_id}.yml")
    import yaml  # type: ignore
    with open(out, "w") as f:
        yaml.dump(rule, f, default_flow_style=False)
    return {"rule_file": out, "rule": rule}

def _sg_ast(ctx: dict) -> dict:
    target = ctx.get("file", "")
    lang   = ctx.get("language", "python")
    try:
        r = _cli([_require("semgrep"), "--dump-ast", "--lang", lang, target])
        return {"ast": r.stdout}
    except Exception as e:
        return _stub_result("semgrep.get_abstract_syntax_tree", ctx, str(e))

def _sg_ci(ctx: dict) -> dict:
    """semgrep ci — diff-aware scan for CI with baseline and reporter."""
    target   = ctx.get("target_path", ".")
    baseline = ctx.get("baseline_ref", "")
    extra    = ctx.get("extra_flags", [])
    try:
        cmd = [_require("semgrep"), "ci", "--json"] + extra
        if baseline:
            cmd += ["--baseline-commit", baseline]
        r = _cli(cmd, cwd=target if Path(target).is_dir() else ".")
        if r.returncode in (0, 1):
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return {"output": r.stdout, "exit_code": r.returncode}
        return {"error": r.stderr, "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("semgrep.semgrep_ci", ctx, str(e))


def _sg_mcp(ctx: dict) -> dict:
    """Start Semgrep MCP server for IDE / agent integration."""
    try:
        r = _cli([_require("semgrep"), "mcp", "--help"])
        return {"command": "semgrep mcp",
                "note": "Run 'semgrep mcp' as a long-running server process.",
                "available": r.returncode == 0}
    except Exception as e:
        return _stub_result("semgrep.semgrep_mcp", ctx, str(e))


def _sg_findings(ctx: dict) -> dict:
    """Retrieve findings from a prior scan result file (SARIF or JSON)."""
    result_file = ctx.get("result_file", "semgrep-results.json")
    sev_filter  = ctx.get("severity", "")
    try:
        data = json.loads(Path(result_file).read_text())
        findings = data.get("results", [])
        if sev_filter:
            findings = [f for f in findings
                        if f.get("extra", {}).get("severity", "").upper() == sev_filter.upper()]
        return {"findings": findings, "count": len(findings), "source": result_file}
    except FileNotFoundError:
        # Try running a fresh scan and capturing results
        ctx2 = dict(ctx, extra_flags=["--output", result_file])
        return _sg_scan(ctx2)
    except Exception as e:
        return _stub_result("semgrep.semgrep_findings", ctx, str(e))


def _sg_rule_schema(ctx: dict) -> dict:
    """Return Semgrep rule YAML schema and supported languages."""
    try:
        r = _cli([_require("semgrep"), "scan", "--help"])
        langs_r = _cli([_require("semgrep"), "languages"])
        return {
            "schema_url": "https://semgrep.dev/docs/writing-rules/rule-syntax/",
            "languages": langs_r.stdout.splitlines() if langs_r.returncode == 0 else [],
            "required_fields": ["id", "patterns", "message", "languages", "severity"],
            "severity_values": ["INFO", "WARNING", "ERROR"],
        }
    except Exception as e:
        return _stub_result("semgrep.get_semgrep_rule_schema", ctx, str(e))


def _sg_stub(name: str):
    return lambda ctx: _stub_result(f"semgrep.{name}", ctx)


SEMGREP_HANDLERS = {
    "semgrep_scan":                  _sg_scan,
    "semgrep_ci":                    _sg_ci,
    "semgrep_login":                 _sg_stub("semgrep_login"),   # requires Semgrep Cloud account
    "semgrep_publish":               _sg_stub("semgrep_publish"), # requires Semgrep Cloud account
    "semgrep_mcp":                   _sg_mcp,
    "semgrep_scan_2":                _sg_scan,
    "semgrep_scan_with_custom_rul":  _sg_scan_custom,
    "semgrep_scan_sca":              _sg_sca,
    "semgrep_findings":              _sg_findings,
    "get_abstract_syntax_tree":      _sg_ast,
    "write_custom_semgrep_rule":     _sg_write_rule,
    "get_semgrep_rule_schema":       _sg_rule_schema,
}

# ══════════════════════════════════════════════════════════════════════════════
#  13. BEARER
# ══════════════════════════════════════════════════════════════════════════════

def _bearer_scan(ctx: dict) -> dict:
    target = ctx.get("target_path", ".")
    fmt    = ctx.get("format",     "json")
    only   = ctx.get("only",       [])
    try:
        cmd = [_require("bearer"), "scan", target, f"--format={fmt}"]
        if only:
            cmd += [f"--only={','.join(only)}"]
        r = _cli(cmd)
        if fmt == "json":
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                pass
        return {"output": r.stdout, "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("bearer.bearer_scan", ctx, str(e))

def _bearer_report(typ: str):
    def _h(ctx: dict) -> dict:
        ctx2 = dict(ctx, only=[typ])
        return _bearer_scan(ctx2)
    return _h

def _bearer_sarif(ctx: dict) -> dict:
    ctx2 = dict(ctx, format="sarif")
    return _bearer_scan(ctx2)

def _bearer_init(ctx: dict) -> dict:
    """bearer init — generate bearer.yml config for the project."""
    target  = ctx.get("target_path", ".")
    scanner = ctx.get("scanner", "secrets,privacy,dataflow,third_party")
    try:
        # bearer init creates .bearer/config.yml
        r = _cli([_require("bearer"), "init", target])
        if r.returncode == 0:
            cfg_path = Path(target) / ".bearer" / "config.yml"
            return {"config_file": str(cfg_path),
                    "exists": cfg_path.exists(),
                    "output": r.stdout}
        # Fallback: write a minimal config
        import os
        cfg_dir = Path(target) / ".bearer"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg = (f"scan:\n  scanner:\n" +
               "".join(f"    - {s}\n" for s in scanner.split(",")))
        (cfg_dir / "config.yml").write_text(cfg)
        return {"config_file": str(cfg_dir / "config.yml"),
                "generated": True, "config": cfg}
    except Exception as e:
        return _stub_result("bearer.bearer_init", ctx, str(e))


def _bearer_ignore(ctx: dict) -> dict:
    """bearer ignore — mark a finding as accepted/false-positive."""
    finding_id = ctx.get("finding_id", "")
    reason     = ctx.get("reason", "false_positive")
    target     = ctx.get("target_path", ".")
    try:
        r = _cli([_require("bearer"), "ignore", "add", finding_id,
                  "--reason", reason], cwd=target)
        return {"exit_code": r.returncode, "finding_id": finding_id,
                "reason": reason, "output": r.stdout}
    except Exception as e:
        return _stub_result("bearer.bearer_ignore", ctx, str(e))


def _bearer_detectors(ctx: dict) -> dict:
    """List detectors available for a given language."""
    lang = ctx.get("language", "")
    try:
        cmd = [_require("bearer"), "scan", "--format=json", "--dry-run",
               "--scanner=secrets,privacy,dataflow"]
        if lang:
            cmd += ["--lang", lang]
        r = _cli(cmd)
        return {"detectors": r.stdout.splitlines()[:50],
                "language": lang,
                "note": "Detectors auto-selected by Bearer based on file extensions."}
    except Exception as e:
        return _stub_result("bearer.detecteurs_par_langage_detec", ctx, str(e))


def _bearer_stub(name: str):
    return lambda ctx: _stub_result(f"bearer.{name}", ctx)


BEARER_HANDLERS = {
    "bearer_scan":                    _bearer_scan,
    "rapport_security":               _bearer_report("secrets"),
    "rapport_privacy":                _bearer_report("privacy"),
    "rapport_dataflow":               _bearer_report("dataflow"),
    "rapport_saas":                   _bearer_report("third_party"),
    "export_sarif":                   _bearer_sarif,
    "bearer_init":                    _bearer_init,
    "bearer_ignore":                  _bearer_ignore,
    "detecteurs_par_langage_detec":   _bearer_detectors,
}

# ══════════════════════════════════════════════════════════════════════════════
#  14. CODEQL
# ══════════════════════════════════════════════════════════════════════════════

def _cql_db_create(ctx: dict) -> dict:
    src  = ctx.get("source",   ".")
    lang = ctx.get("language", "python")
    db   = ctx.get("database", "codeql-db")
    try:
        r = _cli([_require("codeql"), "database", "create", db,
                  "--language", lang, "--source-root", src])
        return {"database": db, "exit_code": r.returncode, "output": r.stdout}
    except Exception as e:
        return _stub_result("codeql.codeql_database_create", ctx, str(e))

def _cql_analyze(ctx: dict) -> dict:
    db   = ctx.get("database", "codeql-db")
    out  = ctx.get("output",   "results.sarif")
    fmt  = ctx.get("format",   "sarif-latest")
    suite = ctx.get("suite",   "")
    cmd  = [_require("codeql"), "database", "analyze", db,
            "--format", fmt, "--output", out]
    if suite:
        cmd.append(suite)
    try:
        r = _cli(cmd)
        if r.returncode == 0 and Path(out).exists():
            return json.loads(Path(out).read_text())
        return {"exit_code": r.returncode, "error": r.stderr}
    except Exception as e:
        return _stub_result("codeql.codeql_database_analyze", ctx, str(e))

def _cql_suite(suite_name: str):
    def _h(ctx: dict) -> dict:
        ctx2 = dict(ctx, suite=suite_name)
        return _cql_analyze(ctx2)
    return _h

def _cql_query_run(ctx: dict) -> dict:
    db    = ctx.get("database", "codeql-db")
    query = ctx.get("query",    "")
    try:
        r = _cli([_require("codeql"), "query", "run", query, "--database", db])
        return {"output": r.stdout, "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("codeql.codeql_query_run", ctx, str(e))

def _cql_pack_install(ctx: dict) -> dict:
    pack = ctx.get("pack", "codeql/python-queries")
    try:
        r = _cli([_require("codeql"), "pack", "download", pack])
        return {"pack": pack, "exit_code": r.returncode}
    except Exception as e:
        return _stub_result("codeql.codeql_pack_download_install", ctx, str(e))

CODEQL_HANDLERS = {
    "codeql_database_create":      _cql_db_create,
    "codeql_database_analyze":     _cql_analyze,
    "codeql_query_run":            _cql_query_run,
    "codeql_pack_download_install":_cql_pack_install,
    "suite_security_extended_qls_":_cql_suite("codeql/python-security-extended"),
    "suite_security_and_quality_q":_cql_suite("codeql/python-security-and-quality"),
    "suite_code_scanning_qls":     _cql_suite("codeql/python-code-scanning"),
}

# ══════════════════════════════════════════════════════════════════════════════
#  15. VIRTUAL NODES
# ══════════════════════════════════════════════════════════════════════════════

def _leon_voice(ctx: dict) -> dict:
    """Simulate or relay a voice command to Leon."""
    text = ctx.get("voice_command") or ctx.get("text", "")
    try:
        import requests
        base = ctx.get("leon_url", "http://localhost:1337")
        r    = requests.post(f"{base}/api/query", json={"query": text})
        return r.json()
    except Exception as e:
        return _stub_result("LEON", ctx, f"Leon not running: {e}")

def _codebase_scan(ctx: dict) -> dict:
    code_path = ctx.get("code_path", ".")
    files     = list(Path(code_path).rglob("*.py")) + \
                list(Path(code_path).rglob("*.ts"))  + \
                list(Path(code_path).rglob("*.go"))
    return {"code_path": code_path, "file_count": len(files),
            "files": [str(f) for f in files[:50]]}

VIRTUAL_HANDLERS = {
    "LEON":           _leon_voice,
    "CODEBASE":       _codebase_scan,
    "CODE_GENERATED": lambda ctx: {"code": ctx.get("code", ""), "path": ctx.get("path", ".")},
    "REPORT":         lambda ctx: {"report": ctx, "format": ctx.get("format", "markdown")},
    "PRODUCTION":     lambda ctx: {"deployed": True, "ctx": ctx},
}

# ── master dispatch table ─────────────────────────────────────────────────────

ALL_HANDLERS: Dict[str, Any] = {}

for _prefix, _hmap in [
    ("q2d",     Q2D_HANDLERS),
    ("likec4",  LIKEC4_HANDLERS),
    ("c4if",    C4IF_HANDLERS),
    ("struct",  STRUCT_HANDLERS),
    ("clab",    CLAB_HANDLERS),
    ("opa",     OPA_HANDLERS),
    ("bf",      BF_HANDLERS),
    ("td",      TD_HANDLERS),
    ("pytm",    PYTM_HANDLERS),
    ("neo4j",   NEO4J_HANDLERS),
    ("tmdd",    TMDD_HANDLERS),
    ("semgrep", SEMGREP_HANDLERS),
    ("bearer",  BEARER_HANDLERS),
    ("codeql",  CODEQL_HANDLERS),
]:
    for _fn, _h in _hmap.items():
        ALL_HANDLERS[f"{_prefix}.{_fn}"] = _h

# Virtual nodes are keyed by their full id (no prefix dot)
ALL_HANDLERS.update(VIRTUAL_HANDLERS)
