"""
nexus_compose.graph
───────────────────
Core types for the NEXUS composability graph.

    ComposabilityGraph  — directed multigraph of Nodes and Edges
    Node                — callable wrapper around a tool function
    Edge                — typed directed connection between two nodes
    NodeResult          — return value of a node execution
    NodeMeta            — static metadata (id, description, io, tag…)
    EdgeType            — semantic type of a connection
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── Edge types ────────────────────────────────────────────────────────────────

class EdgeType(str, Enum):
    DATA_FLOW = "data_flow"   # main pipeline data flow
    TRANSFORM = "transform"   # format conversion
    VALIDATE  = "validate"    # check / assertion
    QUERY     = "query"       # read / interrogate
    INJECT    = "inject"      # constraint injection into agent/LLM
    STORE     = "store"       # persist to graph / DB
    INDIRECT  = "indirect"    # human-mediated bridge
    REPORT    = "report"      # output to report artefact
    SIMULATE  = "simulate"    # network simulation step
    ANALYZE   = "analyze"     # deep semantic analysis

# ── Node metadata ─────────────────────────────────────────────────────────────

@dataclass
class NodeMeta:
    id:          str
    module:      str
    module_name: str
    function:    str
    description: str
    tag:         str
    phase:       str
    type:        str
    io_in:       str
    io_out:      str
    ref:         str
    repo:        str          = ""
    virtual:     bool         = False
    subsection:  Optional[str] = None

# ── Execution result ──────────────────────────────────────────────────────────

@dataclass
class NodeResult:
    node_id:  str
    success:  bool
    data:     Any                   = None
    error:    Optional[str]         = None
    metadata: Dict[str, Any]        = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success

    def raise_if_failed(self) -> "NodeResult":
        if not self.success:
            raise RuntimeError(f"Node {self.node_id} failed: {self.error}")
        return self

# ── Node ─────────────────────────────────────────────────────────────────────

Handler = Callable[[Dict[str, Any]], Any]


class Node:
    """
    A composability node.

    When called with a context dict, it runs its handler and returns a
    NodeResult.  If no live handler is registered the node runs in stub mode,
    logging its intent and returning a sentinel dict.
    """

    def __init__(self, meta: NodeMeta, handler: Optional[Handler] = None):
        self.meta     = meta
        self._handler = handler

    # ── callable ──────────────────────────────────────────────────────────────

    def __call__(self, ctx: Dict[str, Any]) -> NodeResult:
        fn = self._handler or self._stub
        try:
            data = fn(ctx)
            return NodeResult(node_id=self.meta.id, success=True, data=data)
        except Exception as exc:
            logger.warning("[%s] execution failed: %s", self.meta.id, exc)
            return NodeResult(node_id=self.meta.id, success=False, error=str(exc))

    def _stub(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("[STUB] %s | in=%s out=%s", self.meta.id, self.meta.io_in, self.meta.io_out)
        return {
            "_stub":    True,
            "_node":    self.meta.id,
            "_module":  self.meta.module,
            "_phase":   self.meta.phase,
            "_tag":     self.meta.tag,
            "_io_in":   self.meta.io_in,
            "_io_out":  self.meta.io_out,
            "input":    ctx,
        }

    # ── misc ──────────────────────────────────────────────────────────────────

    @property
    def is_live(self) -> bool:
        return self._handler is not None

    def replace_handler(self, handler: Handler) -> None:
        self._handler = handler

    def __repr__(self) -> str:
        live = "live" if self.is_live else "stub"
        return f"Node({self.meta.id!r}, {live})"

# ── Edge ─────────────────────────────────────────────────────────────────────

@dataclass
class Edge:
    source:    str
    target:    str
    label:     str
    type:      EdgeType
    transform: Optional[Callable[[Any], Any]] = None

    def apply(self, data: Any) -> Any:
        """Apply optional edge-level data transform."""
        return self.transform(data) if self.transform else data

    def __repr__(self) -> str:
        return f"Edge({self.source!r} -[{self.type.value}]-> {self.target!r})"

# ── ComposabilityGraph ────────────────────────────────────────────────────────

class ComposabilityGraph:
    """
    Directed multigraph holding all 158 nodes and 197 edges of the NEXUS
    software pipeline composability model.

    Core operations
    ───────────────
    register(node)            add a Node
    connect(edge)             add a directed Edge
    node(id)                  retrieve Node by id
    nodes(module, phase)      iterate nodes, optionally filtered
    successors(id)            outgoing edges from a node
    predecessors(id)          incoming edges to a node
    reachable_forward(id)     set of all nodes reachable downstream
    reachable_backward(id)    set of all nodes reachable upstream
    find_paths(src, tgt)      enumerate simple paths between two nodes
    topological_sort(ids)     Kahn's topo-sort over a subgraph
    """

    def __init__(self):
        self._nodes: Dict[str, Node]        = {}
        self._edges: List[Edge]             = []
        self._out:   Dict[str, List[Edge]]  = {}   # source  → edges out
        self._inp:   Dict[str, List[Edge]]  = {}   # target  → edges in

    # ── registration ──────────────────────────────────────────────────────────

    def register(self, node: Node) -> None:
        self._nodes[node.meta.id] = node
        self._out.setdefault(node.meta.id, [])
        self._inp.setdefault(node.meta.id, [])

    def connect(self, edge: Edge) -> None:
        if edge.source not in self._nodes:
            raise KeyError(f"Unknown source node: {edge.source!r}")
        if edge.target not in self._nodes:
            raise KeyError(f"Unknown target node: {edge.target!r}")
        self._edges.append(edge)
        self._out[edge.source].append(edge)
        self._inp[edge.target].append(edge)

    # ── access ────────────────────────────────────────────────────────────────

    def node(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            ids = list(self._nodes)
            raise KeyError(
                f"Node {node_id!r} not found. "
                f"({len(ids)} nodes registered — use .list_nodes() to inspect)"
            )

    def nodes(
        self,
        module: Optional[str] = None,
        phase:  Optional[str] = None,
        live:   Optional[bool] = None,
    ) -> Iterator[Node]:
        for n in self._nodes.values():
            if module is not None and n.meta.module != module:
                continue
            if phase  is not None and n.meta.phase  != phase:
                continue
            if live   is not None and n.is_live      != live:
                continue
            yield n

    def list_nodes(
        self,
        module: Optional[str] = None,
        phase:  Optional[str] = None,
    ) -> List[str]:
        return [n.meta.id for n in self.nodes(module=module, phase=phase)]

    def edges(self, etype: Optional[EdgeType] = None) -> Iterator[Edge]:
        for e in self._edges:
            if etype is not None and e.type != etype:
                continue
            yield e

    def successors(self, node_id: str) -> List[Edge]:
        return self._out.get(node_id, [])

    def predecessors(self, node_id: str) -> List[Edge]:
        return self._inp.get(node_id, [])

    # ── topology ──────────────────────────────────────────────────────────────

    def reachable_forward(self, node_id: str) -> Set[str]:
        """DFS: all nodes reachable going downstream from node_id."""
        visited: Set[str] = {node_id}
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for e in self._out.get(cur, []):
                if e.target not in visited:
                    visited.add(e.target)
                    stack.append(e.target)
        return visited

    def reachable_backward(self, node_id: str) -> Set[str]:
        """DFS: all nodes that can reach node_id going upstream."""
        visited: Set[str] = {node_id}
        stack = [node_id]
        while stack:
            cur = stack.pop()
            for e in self._inp.get(cur, []):
                if e.source not in visited:
                    visited.add(e.source)
                    stack.append(e.source)
        return visited

    def neighborhood(self, node_id: str) -> Set[str]:
        """Union of forward and backward reachability."""
        return self.reachable_forward(node_id) | self.reachable_backward(node_id)

    def find_paths(
        self,
        source:    str,
        target:    str,
        max_paths: int = 10,
        max_depth: int = 30,
    ) -> List[List[str]]:
        """BFS: enumerate simple paths from source to target."""
        results: List[List[str]] = []
        q: deque = deque([[source]])
        while q and len(results) < max_paths:
            path = q.popleft()
            cur  = path[-1]
            if cur == target:
                results.append(path)
                continue
            if len(path) >= max_depth:
                continue
            for e in self._out.get(cur, []):
                if e.target not in path:
                    q.append(path + [e.target])
        return results

    def shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        paths = self.find_paths(source, target, max_paths=1)
        return paths[0] if paths else None

    def topological_sort(self, node_ids: Optional[List[str]] = None) -> List[str]:
        """
        Kahn's algorithm over a node subgraph (default: all nodes).

        The pipeline contains intentional feedback loops (OPA↔TMDD↔Neo4j).
        When cycles are detected, remaining nodes are appended in DFS order so
        that topological_sort always returns ALL requested nodes.
        """
        ids = set(node_ids) if node_ids else set(self._nodes)
        in_deg: Dict[str, int] = {n: 0 for n in ids}
        for e in self._edges:
            if e.source in ids and e.target in ids:
                in_deg[e.target] += 1

        q      = deque(n for n, d in in_deg.items() if d == 0)
        result: List[str] = []
        while q:
            n = q.popleft()
            result.append(n)
            for e in self._out.get(n, []):
                if e.target in ids:
                    in_deg[e.target] -= 1
                    if in_deg[e.target] == 0:
                        q.append(e.target)

        # Feedback loops: append remaining nodes in DFS order
        if len(result) < len(ids):
            remaining = ids - set(result)
            logger.debug(
                "Feedback loop: appending %d cycled nodes in DFS order", len(remaining)
            )
            visited: set[str] = set(result)

            def _dfs(nid: str) -> None:
                if nid in visited:
                    return
                visited.add(nid)
                result.append(nid)
                for e in self._out.get(nid, []):
                    if e.target in remaining:
                        _dfs(e.target)

            for nid in sorted(remaining):
                _dfs(nid)

        return result

    # ── entry/exit points ─────────────────────────────────────────────────────

    def entry_nodes(self) -> List[str]:
        """Nodes with no incoming edges (pipeline entry points)."""
        return [nid for nid, edges in self._inp.items() if not edges]

    def exit_nodes(self) -> List[str]:
        """Nodes with no outgoing edges (pipeline exit points)."""
        return [nid for nid, edges in self._out.items() if not edges]

    # ── stats ─────────────────────────────────────────────────────────────────

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    def summary(self) -> str:
        mods: Dict[str, int] = {}
        live = 0
        for n in self._nodes.values():
            mods[n.meta.module] = mods.get(n.meta.module, 0) + 1
            if n.is_live:
                live += 1

        etypes: Dict[str, int] = {}
        for e in self._edges:
            etypes[e.type.value] = etypes.get(e.type.value, 0) + 1

        lines = [
            "╔══════════════════════════════════════════════════════╗",
            "║        NEXUS  Composability Graph                    ║",
            "╠══════════════════════════════════════════════════════╣",
            f"║  Nodes : {self.node_count:3d}  ({live} live / {self.node_count-live} stub){'':19}║",
            f"║  Edges : {self.edge_count:3d}{'':43}║",
            "╠═════════════════╤════════╤════════════════╤══════════╣",
            "║ Module          │ Nodes  ║ Edge type      │  Count   ║",
            "╠═════════════════╪════════╬════════════════╪══════════╣",
        ]
        mod_items  = sorted(mods.items())
        etype_items = sorted(etypes.items())
        max_rows   = max(len(mod_items), len(etype_items))
        for i in range(max_rows):
            ml, mc = mod_items[i]  if i < len(mod_items)   else ("", "")
            el, ec = etype_items[i] if i < len(etype_items) else ("", "")
            mc_s = str(mc) if mc != "" else ""
            ec_s = str(ec) if ec != "" else ""
            lines.append(f"║ {ml:15s} │ {mc_s:6s} ║ {el:14s} │ {ec_s:8s} ║")
        lines.append("╚═════════════════╧════════╩════════════════╧══════════╝")
        return "\n".join(lines)
