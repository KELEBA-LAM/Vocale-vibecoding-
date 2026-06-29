"""
nexus_compose.__main__
──────────────────────
CLI:  python -m nexus_compose <command> [options]

Commands
────────
  summary                      Print graph stats
  dry-run [--phase P] [--module M]
  run-node <node_id> [--json '{}']
  run-phase <phase> [--json '{}']
  run-from <entry_id> [--json '{}']
  audit <path>                 Audit-only pipeline on a codebase
  trace <source> <target>
  list-nodes [--module M] [--phase P]
  list-phases
  list-modules
  paths <source> <target>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from nexus_compose import build_graph, Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s  %(name)s  %(message)s",
)


def _ctx(s: str | None) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        print(f"Error: --json must be valid JSON — {e}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m nexus_compose",
        description="NEXUS Composability Orchestrator CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ── summary ───────────────────────────────────────────────────────────────
    sub.add_parser("summary", help="Print graph summary table")

    # ── dry-run ───────────────────────────────────────────────────────────────
    p_dry = sub.add_parser("dry-run", help="Show what would execute")
    p_dry.add_argument("--phase",  default=None)
    p_dry.add_argument("--module", default=None)

    # ── run-node ──────────────────────────────────────────────────────────────
    p_rn = sub.add_parser("run-node", help="Execute a single node")
    p_rn.add_argument("node_id")
    p_rn.add_argument("--json", dest="ctx_json", default=None, metavar="JSON")

    # ── run-phase ─────────────────────────────────────────────────────────────
    p_rp = sub.add_parser("run-phase", help="Execute all nodes in a phase")
    p_rp.add_argument("phase")
    p_rp.add_argument("--json", dest="ctx_json", default=None, metavar="JSON")

    # ── run-from ──────────────────────────────────────────────────────────────
    p_rf = sub.add_parser("run-from", help="Execute pipeline from an entry node")
    p_rf.add_argument("entry_id")
    p_rf.add_argument("--json", dest="ctx_json", default=None, metavar="JSON")

    # ── audit ─────────────────────────────────────────────────────────────────
    p_au = sub.add_parser("audit", help="Run audit-only pipeline on a codebase path")
    p_au.add_argument("path")
    p_au.add_argument("--json", dest="ctx_json", default=None, metavar="JSON")

    # ── trace ─────────────────────────────────────────────────────────────────
    p_tr = sub.add_parser("trace", help="Execute shortest path between two nodes")
    p_tr.add_argument("source")
    p_tr.add_argument("target")
    p_tr.add_argument("--json", dest="ctx_json", default=None, metavar="JSON")

    # ── list-nodes ────────────────────────────────────────────────────────────
    p_ln = sub.add_parser("list-nodes", help="List node IDs")
    p_ln.add_argument("--module", default=None)
    p_ln.add_argument("--phase",  default=None)

    # ── list-phases ───────────────────────────────────────────────────────────
    sub.add_parser("list-phases", help="List all phases present in the graph")

    # ── list-modules ──────────────────────────────────────────────────────────
    sub.add_parser("list-modules", help="List all modules present in the graph")

    # ── paths ─────────────────────────────────────────────────────────────────
    p_pa = sub.add_parser("paths", help="Enumerate simple paths between two nodes")
    p_pa.add_argument("source")
    p_pa.add_argument("target")
    p_pa.add_argument("--max", dest="max_paths", type=int, default=5)

    args = parser.parse_args(argv)

    # ── bootstrap ─────────────────────────────────────────────────────────────
    print("Building composability graph …", flush=True)
    G    = build_graph()
    orch = Orchestrator(G)

    # ── dispatch ──────────────────────────────────────────────────────────────

    if args.cmd == "summary":
        print(G.summary())

    elif args.cmd == "dry-run":
        ids = None
        if args.phase or args.module:
            ids = G.list_nodes(module=args.module, phase=args.phase)
        report = orch.dry_run(ids)
        print(report)

    elif args.cmd == "run-node":
        result = orch.run_node(args.node_id, _ctx(args.ctx_json))
        status = "✓" if result.success else "✗"
        print(f"{status}  {args.node_id}")
        if result.error:
            print(f"   Error: {result.error}", file=sys.stderr)
        else:
            print(json.dumps(result.data, indent=2, default=str))

    elif args.cmd == "run-phase":
        pr = orch.run_phase(args.phase, _ctx(args.ctx_json))
        print(pr.summary())
        sys.exit(0 if pr.success else 1)

    elif args.cmd == "run-from":
        pr = orch.run_from(args.entry_id, _ctx(args.ctx_json))
        print(pr.summary())
        sys.exit(0 if pr.success else 1)

    elif args.cmd == "audit":
        pr = orch.audit_only_pipeline(args.path, _ctx(args.ctx_json))
        print(pr.summary())
        sys.exit(0 if pr.success else 1)

    elif args.cmd == "trace":
        trace = orch.trace(args.source, args.target, _ctx(args.ctx_json))
        print(trace.summary())
        sys.exit(0 if trace.found else 1)

    elif args.cmd == "list-nodes":
        nodes = G.list_nodes(module=args.module, phase=args.phase)
        for nid in nodes:
            print(nid)
        print(f"\n{len(nodes)} nodes")

    elif args.cmd == "list-phases":
        phases = sorted({n.meta.phase for n in G.nodes() if n.meta.phase})
        for p in phases:
            count = len(G.list_nodes(phase=p))
            print(f"  {p:12s}  {count:3d} nodes")

    elif args.cmd == "list-modules":
        mods: dict[str, int] = {}
        for n in G.nodes():
            mods[n.meta.module] = mods.get(n.meta.module, 0) + 1
        for mod, cnt in sorted(mods.items()):
            name = next(G.nodes(module=mod)).meta.module_name
            print(f"  {mod:10s}  {name:24s}  {cnt:3d} nodes")

    elif args.cmd == "paths":
        paths = G.find_paths(args.source, args.target, max_paths=args.max_paths)
        if not paths:
            print(f"No paths found from {args.source} to {args.target}")
            sys.exit(1)
        for i, path in enumerate(paths, 1):
            print(f"\nPath {i} ({len(path)} steps):")
            print("  " + "  →\n  ".join(path))


if __name__ == "__main__":
    main()
