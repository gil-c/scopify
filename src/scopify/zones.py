"""Zone analysis: derive layers from the import graph and report the knots.

Scopify already knows how to say *who may use a symbol*. This module answers
the other half of the question C# solves with projects and Rust with crates:
*which part of the code may depend on which other part*.

The design comes from measuring five real projects (httpx, flask, werkzeug,
pytest, scrapy). Three findings shape it:

* **Zones must come from directories, not from the graph.** Community
  detection scores well but is not reproducible: adding a file redistributes
  unrelated modules. Anchoring a zone to a path makes the split depend only on
  where a file lives — 99.9 % of module pairs keep the same grouping when a
  file is removed.
* **The goal is not "fewer dependencies across borders".** That measure is
  minimal (0 %) for a single zone, so optimising it collapses everything into
  one blob. The goal is *layers without cycles*.
* **A registry is not a dependency.** ``_pytest/config`` names 27 plugins in a
  tuple and those plugins import the configuration back. Counting both
  directions invents 14 cycles that no one should fix.

The output is deliberately a diagnostic command, not a CI gate: removing a
module that half the project imports does move the reported knots around, and
failing a build on that would punish the wrong commit.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from scopify.config import ScopifyConfig, load_config
from scopify.engine import ProjectIndex, build_index
from scopify.imports import collect_imports

# ---------------------------------------------------------------------------
# graph
# ---------------------------------------------------------------------------

RUNTIME = "runtime"
TYPING = "typing"
REGISTRY = "registry"

#: An import that only serves annotations is a weaker coupling than one the
#: interpreter must satisfy; an import buried in a function is a cycle its
#: author already worked around by hand.
KIND_RUNTIME = "runtime coupling"
KIND_ANNOTATION = "annotation only"
KIND_DEFERRED = "import inside a function"
#: A package importing its own submodule from its ``__init__.py`` is the door
#: publishing what it contains. It closes a circle — the submodule imports the
#: base class back — but there is no other way to write a facade, so it must
#: not read like the others.
KIND_DOOR = "package door re-export"
#: Marks the zone made of a package's own ``__init__.py``.
DOOR_SUFFIX = " (door)"


@dataclass(frozen=True)
class Edge:
    """One dependency between two modules of the project."""

    source: str
    target: str
    symbol: str | None
    nature: str            # RUNTIME | TYPING | REGISTRY
    line: int
    file: Path
    top_level: bool = True
    annotation_only: bool = False
    door_reexport: bool = False

    @property
    def kind(self) -> str:
        if self.door_reexport:
            return KIND_DOOR
        if not self.top_level:
            return KIND_DEFERRED
        if self.annotation_only:
            return KIND_ANNOTATION
        return KIND_RUNTIME


@dataclass
class Knot:
    """A group of zones that depend on each other in a circle.

    ``edges`` holds only the imports that point *upwards* inside the knot, in
    the order chosen locally: those are the ones a reader can act on. The knot
    itself, ``zones``, is the stable fact and gives them their context.
    """

    zones: tuple[str, ...]
    edges: tuple[Edge, ...]

    @property
    def size(self) -> int:
        return len(self.zones)

    @property
    def domains(self) -> tuple[str, ...]:
        """The zones rolled up to the folder they live in.

        A knot of twenty-four zones is unreadable, and most of them are
        siblings: on scrapy it collapses to six folders, which is the
        sentence a maintainer can act on. On a flat package there is no
        folder to roll up to, so this returns the zones unchanged.
        """
        rolled = set()
        for zone in self.zones:
            parts = zone.replace(DOOR_SUFFIX, "").split(".")
            rolled.add(".".join(parts[:2]) if len(parts) > 1 else parts[0])
        return tuple(sorted(rolled))

    def by_cause(self) -> list[tuple[str, str, tuple[Edge, ...]]]:
        """Group the imports by the pair of zones they connect.

        Twenty-six imports of ``Spider`` scattered over scrapy are one cause
        and one fix, not twenty-six red lines.
        """
        grouped: dict[tuple[str, str], list[Edge]] = defaultdict(list)
        for edge in self.edges:
            grouped[(self._zone_of[edge.source], self._zone_of[edge.target])].append(edge)
        return [
            (source, target, tuple(found))
            for (source, target), found in sorted(
                grouped.items(),
                key=lambda item: (
                    all(edge.door_reexport for edge in item[1]),
                    -len(item[1]),
                    item[0],
                ),
            )
        ]

    _zone_of: dict[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Export:
    """A symbol one zone defines and another zone imports.

    This is the surface a zone would have to publish for the rest of the
    project to keep working — the equivalent of a C# project's ``public``,
    read off what the code actually does rather than declared upfront.
    """

    symbol: str
    module: str                      # where it is defined
    zone: str                        # the zone that owns it
    consumers: tuple[str, ...] = ()  # the other zones importing it

    @property
    def reach(self) -> int:
        return len(self.consumers)


@dataclass
class ZoneReport:
    root: Path
    zones: dict[str, str] = field(default_factory=dict)      # module -> zone
    levels: dict[str, int] = field(default_factory=dict)     # zone -> layer
    knots: list[Knot] = field(default_factory=list)
    registries: dict[str, str] = field(default_factory=dict)  # plugin -> registry
    exports: list[Export] = field(default_factory=list)

    def exports_by_zone(self) -> dict[str, list[Export]]:
        """The exposed surface of each zone, widest reach first."""
        out: dict[str, list[Export]] = defaultdict(list)
        for export in self.exports:
            out[export.zone].append(export)
        return {
            zone: sorted(found, key=lambda e: (-e.reach, e.symbol))
            for zone, found in out.items()
        }

    def members(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for module, zone in self.zones.items():
            out[zone].append(module)
        return {z: sorted(ms) for z, ms in out.items()}


def _annotation_only_names(tree: ast.AST) -> set[str]:
    """Names used exclusively inside type annotations."""
    annotations: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.arg, ast.AnnAssign)) and node.annotation is not None:
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
            annotations.append(node.returns)
    inside: set[str] = set()
    annotated_ids: set[int] = set()
    for annotation in annotations:
        for sub in ast.walk(annotation):
            annotated_ids.add(id(sub))
            if isinstance(sub, ast.Name):
                inside.add(sub.id)
    outside = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and id(node) not in annotated_ids
        and not isinstance(node.ctx, ast.Store)
    }
    return inside - outside


def _resolve_registry_string(text: str, modules: set[str], prefixes: list[str]) -> str | None:
    """Resolve a string literal to a module of the project, if it names one.

    Handles the three spellings found in the wild: ``"_pytest.python"``,
    ``"python"`` (implicit package prefix) and
    ``"scrapy.downloadermiddlewares.retry.RetryMiddleware"`` (a class path, so
    trailing segments have to be dropped).
    """
    text = text.split(":")[0].strip()
    if not text or " " in text or "/" in text:
        return None
    for candidate in [text] + [f"{prefix}.{text}" for prefix in prefixes]:
        parts = candidate.split(".")
        while parts:
            joined = ".".join(parts)
            # A bare package name is not a useful dependency.
            if joined in modules and joined not in prefixes:
                return joined
            parts.pop()
    return None


def _registry_targets(tree: ast.AST, modules: set[str], prefixes: list[str]) -> set[str]:
    """Modules named inside a module-level list, tuple, set or dict literal.

    Restricted on purpose. Scanning every string literal picks up docstrings
    and error messages, which are not dependencies; requiring a declared
    container yields nothing on httpx, flask and werkzeug — which have no
    registry — and exactly the plugin tables of pytest and scrapy.
    """
    found: set[str] = set()
    for stmt in getattr(tree, "body", []):
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            continue
        value = stmt.value
        if not isinstance(value, (ast.List, ast.Tuple, ast.Set, ast.Dict)):
            continue
        for node in ast.walk(value):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                resolved = _resolve_registry_string(node.value, modules, prefixes)
                if resolved is not None:
                    found.add(resolved)
    return found


def _door_map(index: ProjectIndex, modules: set[str]) -> dict[tuple[str, str], str]:
    """``(package, name) -> module where the name is actually defined``.

    A package door is not a layer. ``from scrapy import Request`` reads as a
    dependency on ``scrapy``, which sits at the top of the stack, when the real
    dependency is on ``scrapy.http.request`` near the bottom. Left uncorrected,
    every re-export looks like an upward dependency.
    """
    door: dict[tuple[str, str], str] = {}
    for module in sorted(modules):
        path = index.files_by_module.get(module)
        source = index.sources_by_module.get(module)
        if path is None or source is None or path.name != "__init__.py":
            continue
        for ref in collect_imports(source, module, is_package=True):
            name = ref.imported_name
            if not name or name == "*":
                continue
            target = ref.from_module
            real = f"{target}.{name}" if f"{target}.{name}" in modules else target
            if real in modules and real != module:
                door[(module, name)] = real
    # A door may itself re-export from another door.
    for _ in range(3):
        for (package, name), target in list(door.items()):
            chained = door.get((target, name))
            if chained is not None and chained != target:
                door[(package, name)] = chained
    return door


def project_prefixes(index: ProjectIndex, config: ScopifyConfig) -> list[str]:
    """Top-level packages to analyse: the configured roots, else what exists."""
    if config.roots:
        return sorted(config.roots)
    return sorted({module.split(".")[0] for module in index.files_by_module})


def build_edges(index: ProjectIndex, prefixes: list[str]) -> list[Edge]:
    """Every dependency between modules of the project, corrected and typed."""
    modules = {
        module
        for module in index.files_by_module
        if any(module == p or module.startswith(p + ".") for p in prefixes)
    }
    doors = _door_map(index, modules)
    edges: list[Edge] = []

    for module in sorted(modules):
        source = index.sources_by_module.get(module)
        path = index.files_by_module.get(module)
        if source is None or path is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        is_package = path.name == "__init__.py"
        annotation_only = _annotation_only_names(tree)

        seen: set[str] = set()
        for ref in collect_imports(source, module, is_package=is_package):
            target = ref.from_module
            name = ref.imported_name
            if name and f"{target}.{name}" in modules:
                # ``from . import cli`` depends on the submodule, not on the
                # package: pointing it at the package fabricates arrows into
                # the door that nobody wrote.
                target = f"{target}.{name}"
            elif not is_package and name and (target, name) in doors:
                target = doors[(target, name)]
            if target not in modules or target == module:
                continue
            seen.add(target)
            edges.append(
                Edge(
                    source=module,
                    target=target,
                    symbol=name,
                    nature=TYPING if ref.type_checking else RUNTIME,
                    line=ref.lineno,
                    file=path,
                    top_level=ref.top_level,
                    annotation_only=bool(name and name in annotation_only),
                    door_reexport=is_package and target.startswith(module + "."),
                )
            )

        for target in sorted(_registry_targets(tree, modules, prefixes) - seen - {module}):
            edges.append(
                Edge(module, target, None, REGISTRY, 0, path)
            )
    return edges


# ---------------------------------------------------------------------------
# zones and layers
# ---------------------------------------------------------------------------


def zones_by_directory(modules: set[str], prefixes: list[str]) -> dict[str, str]:
    """One zone per directory, one level below the package root.

    The package door keeps a zone of its own: it is not a layer, it cuts
    across all of them.
    """
    zones: dict[str, str] = {}
    for module in modules:
        candidates = [p for p in prefixes if module == p or module.startswith(p + ".")]
        if not candidates:
            continue
        prefix = max(candidates, key=len)
        if module == prefix:
            zones[module] = prefix + DOOR_SUFFIX
            continue
        head = module[len(prefix) + 1:].split(".")[0]
        zones[module] = f"{prefix}.{head}"
    return zones


def zone_weights(
    edges: list[Edge], zones: dict[str, str], *, include_registry: bool = False
) -> dict[tuple[str, str], int]:
    """Distinct symbols crossing each zone border."""
    skipped = {TYPING} if include_registry else {TYPING, REGISTRY}
    crossing: dict[tuple[str, str], set[str]] = defaultdict(set)
    for edge in edges:
        if edge.nature in skipped:
            continue
        source, target = zones.get(edge.source), zones.get(edge.target)
        if source is None or target is None or source == target:
            continue
        crossing[(source, target)].add(f"{edge.target}:{edge.symbol or '*'}")
    return {pair: len(symbols) for pair, symbols in crossing.items()}


def strongly_connected(
    nodes: set[str], weights: dict[tuple[str, str], int]
) -> list[frozenset[str]]:
    """Groups of mutually reachable zones, largest first (iterative Tarjan)."""
    successors: dict[str, list[str]] = {node: [] for node in nodes}
    for source, target in sorted(weights):
        if source in successors and target in nodes:
            successors[source].append(target)

    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    counter = 0
    groups: list[frozenset[str]] = []

    for start in sorted(nodes):
        if start in index_of:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, child = work[-1]
            if child == 0:
                index_of[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recursed = False
            for position in range(child, len(successors[node])):
                nxt = successors[node][position]
                if nxt not in index_of:
                    work[-1] = (node, position + 1)
                    work.append((nxt, 0))
                    recursed = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
            if recursed:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index_of[node]:
                group: set[str] = set()
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.add(member)
                    if member == node:
                        break
                if len(group) > 1:
                    groups.append(frozenset(group))
    return sorted(groups, key=lambda g: (-len(g), sorted(g)))


def order_zones(nodes: set[str], weights: dict[tuple[str, str], int]) -> list[str]:
    """Linear order minimising the weight of dependencies that point upwards.

    Eades, Lin & Smyth (1993). Ties are broken alphabetically, so the result is
    reproducible and a rename can only move a zone among equals.
    """
    remaining = set(nodes)
    out_weight: dict[str, int] = defaultdict(int)
    in_weight: dict[str, int] = defaultdict(int)
    successors: dict[str, dict[str, int]] = defaultdict(dict)
    predecessors: dict[str, dict[str, int]] = defaultdict(dict)
    for (source, target), weight in weights.items():
        if source == target or source not in nodes or target not in nodes:
            continue
        successors[source][target] = weight
        predecessors[target][source] = weight
        out_weight[source] += weight
        in_weight[target] += weight

    head: list[str] = []
    tail: list[str] = []

    def remove(node: str) -> None:
        remaining.discard(node)
        for other, weight in successors[node].items():
            if other in remaining:
                in_weight[other] -= weight
        for other, weight in predecessors[node].items():
            if other in remaining:
                out_weight[other] -= weight

    while remaining:
        moved = True
        while moved:
            moved = False
            for node in sorted(remaining):
                if out_weight[node] == 0:       # depends on nothing: bedrock
                    tail.append(node)
                    remove(node)
                    moved = True
                    break
            for node in sorted(remaining):
                if node in remaining and in_weight[node] == 0:  # nothing needs it
                    head.append(node)
                    remove(node)
                    moved = True
                    break
        if remaining:
            node = max(sorted(remaining), key=lambda n: out_weight[n] - in_weight[n])
            head.append(node)
            remove(node)
    return head + tail[::-1]


def layer_levels(order: list[str], weights: dict[tuple[str, str], int]) -> dict[str, int]:
    """Layer of each zone. 0 is the bedrock; same level means independent."""
    rank = {zone: position for position, zone in enumerate(order)}
    downward: dict[str, list[str]] = defaultdict(list)
    for source, target in weights:
        if source in rank and target in rank and rank[source] < rank[target]:
            downward[source].append(target)
    levels: dict[str, int] = {}
    for zone in reversed(order):
        levels[zone] = 1 + max(
            (levels[target] for target in downward[zone] if target in levels),
            default=-1,
        )
    return levels


def split_zone(zones: dict[str, str], zone: str) -> bool:
    """Split one zone one directory level deeper. Never merges."""
    members = [module for module, name in zones.items() if name == zone]
    if len(members) <= 1:
        return False
    depth = zone.count(".") + 1
    changed = False
    for module in members:
        parts = module.split(".")
        deeper = ".".join(parts[: depth + 1]) if len(parts) > depth else module
        if deeper != zone:
            zones[module] = deeper
            changed = True
    return changed


def refine_zones(
    edges: list[Edge], zones: dict[str, str], *, max_steps: int = 12
) -> dict[str, str]:
    """Split directories that mix two layers, until none is left in a cycle.

    ``werkzeug/sansio`` holds ``utils`` and ``http`` near the bottom and
    ``request``/``response`` near the top; kept whole it manufactures upward
    dependencies that are an artefact of the directory, not of the code.

    Every zone caught in a cycle is split, all at once. An earlier version
    picked "the worst zone first", which is a *global* decision: removing one
    file changed the split order and moved warnings to the other end of the
    project.
    """
    zones = dict(zones)
    for _ in range(max_steps):
        weights = zone_weights(edges, zones)
        tangled = {
            zone
            for group in strongly_connected(set(zones.values()), weights)
            for zone in group
        }
        if not tangled:
            break
        if not any(split_zone(zones, zone) for zone in sorted(tangled)):
            break
    return zones


def find_knots(edges: list[Edge], zones: dict[str, str]) -> list[Knot]:
    """Zones that depend on each other in a circle, with the imports at fault.

    The knot itself is the stable fact and is reported whole. Inside it, an
    order is chosen *locally* — only among the zones of that knot — to decide
    which imports point upwards. Keeping the choice local is what keeps the
    output steady: a change elsewhere in the project cannot move it.
    """
    weights = zone_weights(edges, zones)
    groups = strongly_connected(set(zones.values()), weights)
    membership = {zone: group for group in groups for zone in group}

    local_rank: dict[str, int] = {}
    for group in groups:
        inner = {
            pair: weight
            for pair, weight in weights.items()
            if pair[0] in group and pair[1] in group
        }
        for position, zone in enumerate(order_zones(set(group), inner)):
            local_rank[zone] = position

    collected: dict[frozenset[str], list[Edge]] = {group: [] for group in groups}
    for edge in edges:
        if edge.nature != RUNTIME:
            continue
        source, target = zones.get(edge.source), zones.get(edge.target)
        if source is None or target is None or source == target:
            continue
        group = membership.get(source)
        if group is None or group is not membership.get(target):
            continue
        if local_rank[source] < local_rank[target]:
            continue                       # points down: nothing to say
        collected[group].append(edge)

    knots = [
        Knot(
            zones=tuple(sorted(group)),
            edges=tuple(sorted(found, key=lambda e: (e.source, e.line))),
            _zone_of={
                module: zone for module, zone in zones.items() if zone in group
            },
        )
        for group, found in collected.items()
    ]
    return sorted(knots, key=lambda k: (-len(k.edges), k.zones))


def exported_surface(
    index: ProjectIndex, modules: set[str], zones: dict[str, str]
) -> list[Export]:
    """The symbols each zone hands to another zone.

    Read off the imports, so it is a *lower bound*: anything reached
    dynamically is invisible here, and a symbol meant to be shared but not
    yet used by anyone does not show up.

    Unlike the dependency graph, this counts every import — including the
    ones under ``if TYPE_CHECKING:`` and inside functions. Those do not
    create a load-time cycle, but they are still uses, and a zone that
    stopped exposing them would break its consumers.
    """
    consumers: dict[tuple[str, str], set[str]] = defaultdict(set)
    for module in sorted(modules):
        source = index.sources_by_module.get(module)
        file = index.files_by_module.get(module)
        if source is None or file is None:
            continue
        for ref in collect_imports(
            source, module, is_package=file.name == "__init__.py"
        ):
            name = ref.imported_name
            if name in (None, "*") or ref.from_module not in modules:
                continue
            if ref.from_module == module:
                continue
            home, user = zones.get(ref.from_module), zones.get(module)
            if home is None or user is None or home == user:
                continue
            consumers[(ref.from_module, name)].add(user)

    return sorted(
        (
            Export(
                symbol=symbol,
                module=owner,
                zone=zones[owner],
                consumers=tuple(sorted(found)),
            )
            for (owner, symbol), found in consumers.items()
        ),
        key=lambda e: (e.zone, -e.reach, e.symbol),
    )


def analyse(root: Path, config: ScopifyConfig | None = None) -> ZoneReport:
    root = Path(root).resolve()
    if config is None:
        config = load_config(root)
    index = build_index(root, config=config)
    prefixes = project_prefixes(index, config)
    edges = build_edges(index, prefixes)
    modules = {
        module
        for module in index.files_by_module
        if any(module == p or module.startswith(p + ".") for p in prefixes)
    }
    zones = refine_zones(edges, zones_by_directory(modules, prefixes))
    weights = zone_weights(edges, zones)
    order = order_zones(set(zones.values()), weights)
    return ZoneReport(
        root=root,
        zones=zones,
        levels=layer_levels(order, weights),
        knots=find_knots(edges, zones),
        registries={
            edge.target: edge.source for edge in edges if edge.nature == REGISTRY
        },
        exports=exported_surface(index, modules, zones),
    )


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


#: A zone handing out more than this many symbols is not a zone any more.
#: Measured on the corpus: the median zone exposes 2, and every project has
#: at most one or two outliers well past this line (``scrapy.utils`` at 119).
#: It is a reading aid, never a threshold anything fails on.
WIDE_SURFACE = 20


def format_coupling(report: ZoneReport) -> str:
    """What each zone hands to the rest of the project.

    This is the modularity read: a zone with a small, stable surface is a
    zone; one handing out a hundred names is a drawer everything reaches
    into, and no dependency rule will fix that.
    """
    lines: list[str] = []
    by_zone = report.exports_by_zone()
    members = report.members()
    silent = [zone for zone in members if zone not in by_zone]

    total = len(report.exports)
    lines.append(
        f"scopify: {len(by_zone)} of {len(members)} zone(s) hand out "
        f"{total} symbol(s) to the rest of the project."
    )
    lines.append("")
    for zone, exports in sorted(by_zone.items(), key=lambda kv: -len(kv[1])):
        widest = exports[0]
        lines.append(
            f"  {zone}  ({len(members[zone])} module(s), "
            f"exposes {len(exports)})"
        )
        for export in exports[:6]:
            lines.append(
                f"      {export.symbol}  used by {export.reach} zone(s)"
                f"  [{export.module}]"
            )
        if len(exports) > 6:
            lines.append(f"      ... and {len(exports) - 6} more")
        if len(exports) > WIDE_SURFACE:
            lines.append(
                f"      ! {len(exports)} symbols is not an interface, it is a "
                "drawer. Split this zone,"
            )
            lines.append(
                "        or accept that the rest of the project depends on all "
                "of it."
            )
        if widest.reach >= 10:
            lines.append(
                f"      ! {widest.symbol} is reached by {widest.reach} zones. "
                "Either it is a pillar"
            )
            lines.append(
                "        and belongs in the published API, or it is a "
                "crossroads worth breaking up."
            )

    if silent:
        if total:
            lines.append("")
        lines.append(
            f"  {len(silent)} zone(s) hand out nothing: "
            f"{', '.join(sorted(silent)[:8])}"
            + (" ..." if len(silent) > 8 else "")
        )
        lines.append(
            "  Either well sealed, or dead code. scopify cannot tell the "
            "difference."
        )
    return "\n".join(lines)


def _zone_key(zone: str, taken: set[str]) -> str:
    """A short, legal TOML key for a zone, unique within the file."""
    stem = zone.removesuffix(DOOR_SUFFIX).strip()
    parts = [piece for piece in stem.split(".") if piece]
    name = "_".join(parts[1:]) if len(parts) > 1 else (parts[0] if parts else "zone")
    name = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
    name = name.lstrip("_") or "zone"
    candidate, suffix = name, 2
    while candidate in taken:
        candidate, suffix = f"{name}_{suffix}", suffix + 1
    taken.add(candidate)
    return candidate


def zone_block(report: ZoneReport, package: str) -> str:
    """The TOML declaration for one package, ready to paste.

    Used by the SC020 quick fix: the diagnostic sits on a package's
    ``__init__.py``, the fix belongs in ``pyproject.toml``. ``exposes`` is
    filled from what the rest of the project already imports, so accepting
    the fix changes no behaviour — it only writes down what is true today.
    """
    by_zone = report.exports_by_zone()
    owned = [
        zone
        for zone in report.members()
        if zone == package or zone.startswith(f"{package}.")
    ]
    symbols = sorted(
        {export.symbol for zone in owned for export in by_zone.get(zone, [])}
    )
    key = _zone_key(package, set())
    exposes = ", ".join(f'"{name}"' for name in symbols)
    return (
        f"[tool.scopify.zones.{key}]\n"
        f'modules = ["{package}", "{package}.**"]\n'
        f"exposes = [{exposes}]\n"
    )


def format_config(report: ZoneReport) -> str:
    """The zone declaration scopify would write for this project.

    Deduced from what the code already does, so pasting it changes nothing
    on day one. Two limits worth stating out loud, both understatements:
    the surface is read from *static* imports, so anything reached
    dynamically is missing, and ``exposes`` reflects use, not intent — a
    symbol meant to be shared but not used yet will not appear.
    """
    by_zone = report.exports_by_zone()
    members = report.members()
    lines = [
        "# Generated by 'scopify zones --init'.",
        "# Deduced from the imports this project already makes, so it",
        "# describes today rather than prescribing tomorrow. Rename the",
        "# zones, merge them, and trim 'exposes' until it reads like an",
        "# interface you would defend.",
        "",
    ]
    taken: set[str] = set()
    for zone in sorted(members):
        modules = members[zone]
        exports = by_zone.get(zone, [])
        lines.append(f"[tool.scopify.zones.{_zone_key(zone, taken)}]")
        patterns = sorted({zone, f"{zone}.**"}) if len(modules) > 1 else list(modules)
        rendered = ", ".join(f'"{pattern}"' for pattern in patterns)
        lines.append(f"modules = [{rendered}]")
        if exports:
            names = ", ".join(f'"{export.symbol}"' for export in exports)
            lines.append(f"exposes = [{names}]")
        else:
            lines.append("exposes = []")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_text(report: ZoneReport, *, show_layers: bool = True) -> str:
    """Human-readable report: the layers, then the knots and what ties them."""
    lines: list[str] = []
    members = report.members()
    layers = len({level for level in report.levels.values()})
    lines.append(
        f"scopify: {len(members)} zone(s) over {layers} layer(s) "
        f"in {len(report.zones)} module(s)."
    )

    if show_layers:
        lines.append("")
        by_level: dict[int, list[str]] = defaultdict(list)
        for zone, level in report.levels.items():
            by_level[level].append(zone)
        for level in sorted(by_level, reverse=True):
            names = ", ".join(sorted(by_level[level]))
            lines.append(f"  layer {level:>2}  {names}")

    if report.registries:
        registries = sorted(set(report.registries.values()))
        lines.append("")
        lines.append(
            f"  {len(report.registries)} module(s) are loaded by name from "
            f"{', '.join(registries)}."
        )
        lines.append(
            "  They are wired at run time, not by an import: scopify counts "
            "them as dependencies"
        )
        lines.append(
            "  of the registry, and does not report the plugins importing it back."
        )

    if not report.knots:
        lines.append("")
        lines.append("  No dependency knot: every zone can be placed in a layer.")
        return "\n".join(lines)

    total = sum(len(knot.edges) for knot in report.knots)
    doors = sum(
        1 for knot in report.knots for edge in knot.edges if edge.door_reexport
    )
    lines.append("")
    lines.append(
        f"  {len(report.knots)} dependency knot(s), {total} import(s) to look at."
    )
    if doors:
        lines.append(
            f"  {doors} of them are a package publishing its own submodules, "
            "listed last: a facade"
        )
        lines.append(
            "  cannot be written without them, so read the others first."
        )
    for knot in report.knots:
        lines.append("")
        domains = knot.domains
        if len(domains) < knot.size:
            lines.append(
                f"  ! {knot.size} zones depend on each other in a circle, "
                f"across {len(domains)}: {', '.join(domains)}"
            )
        else:
            lines.append(
                f"  ! {knot.size} zones depend on each other in a circle: "
                f"{', '.join(knot.zones)}"
            )
        for source, target, found in knot.by_cause():
            lines.append(f"      {source} -> {target}  ({len(found)} import(s))")
            for edge in found:
                where = f"{_relative(edge.file, report.root)}:{edge.line}"
                lines.append(
                    f"        {where}  {edge.symbol or edge.target}  [{edge.kind}]"
                )
    return "\n".join(lines)


def to_dict(report: ZoneReport) -> dict:
    """JSON-friendly view of the report."""
    return {
        "zones": [
            {
                "name": zone,
                "layer": report.levels.get(zone, 0),
                "modules": modules,
                "exposes": [
                    {
                        "symbol": export.symbol,
                        "module": export.module,
                        "consumers": list(export.consumers),
                    }
                    for export in report.exports_by_zone().get(zone, [])
                ],
            }
            for zone, modules in sorted(report.members().items())
        ],
        "registries": [
            {"module": module, "registry": registry}
            for module, registry in sorted(report.registries.items())
        ],
        "knots": [
            {
                "zones": list(knot.zones),
                "imports": [
                    {
                        "file": _relative(edge.file, report.root),
                        "line": edge.line,
                        "source": edge.source,
                        "target": edge.target,
                        "symbol": edge.symbol,
                        "kind": edge.kind,
                    }
                    for edge in knot.edges
                ],
            }
            for knot in report.knots
        ],
    }
