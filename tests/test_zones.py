from __future__ import annotations

from pathlib import Path

from scopify.config import load_config
from scopify.engine import build_index
from scopify.zones import (
    KIND_ANNOTATION,
    KIND_DEFERRED,
    KIND_DOOR,
    KIND_RUNTIME,
    analyse,
    build_edges,
    format_text,
    project_prefixes,
    to_dict,
)


def write(root: Path, files: dict[str, str]) -> Path:
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return root


def kinds_of(root: Path) -> dict[str, str]:
    """The kind scopify puts on each import, by imported symbol."""
    config = load_config(root)
    index = build_index(root, config=config)
    edges = build_edges(index, project_prefixes(index, config))
    return {edge.symbol: edge.kind for edge in edges if edge.symbol}


def test_layers_without_a_cycle(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/base.py": "VALUE = 1\n",
            "app/middle.py": "from app.base import VALUE\n",
            "app/top.py": "from app.middle import VALUE\n",
        },
    )
    report = analyse(tmp_path)
    assert report.knots == []
    assert report.levels["app.base"] < report.levels["app.middle"]
    assert report.levels["app.middle"] < report.levels["app.top"]
    assert "No dependency knot" in format_text(report)


def test_a_cycle_is_reported_with_its_imports(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/one.py": "from app.two import B\n\n\nclass A:\n    pass\n",
            "app/two.py": "from app.one import A\n\n\nclass B:\n    pass\n",
        },
    )
    report = analyse(tmp_path)
    assert len(report.knots) == 1
    knot = report.knots[0]
    assert knot.zones == ("app.one", "app.two")
    # Only the import that closes the circle is reported, not both sides.
    assert len(knot.edges) == 1
    assert knot.edges[0].kind == KIND_RUNTIME
    assert kinds_of(tmp_path) == {"A": KIND_RUNTIME, "B": KIND_RUNTIME}


def test_a_type_checking_import_does_not_create_a_cycle(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/one.py": (
                "from typing import TYPE_CHECKING\n"
                "\n"
                "if TYPE_CHECKING:\n"
                "    from app.two import B\n"
            ),
            "app/two.py": "from app.one import A\n\n\nclass B:\n    pass\n",
        },
    )
    assert analyse(tmp_path).knots == []


def test_an_import_inside_a_function_is_named_as_such(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/one.py": (
                "class A:\n"
                "    def go(self):\n"
                "        from app.two import B\n"
                "        return B\n"
            ),
            "app/two.py": "from app.one import A\n\n\nclass B:\n    pass\n",
        },
    )
    assert kinds_of(tmp_path) == {"B": KIND_DEFERRED, "A": KIND_RUNTIME}


def test_an_annotation_only_import_is_named_as_such(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/one.py": (
                "from app.two import B\n"
                "\n"
                "\n"
                "class A:\n"
                "    def go(self, value: B) -> None:\n"
                "        pass\n"
            ),
            "app/two.py": "from app.one import A\n\n\nclass B:\n    pass\n",
        },
    )
    assert kinds_of(tmp_path)["B"] == KIND_ANNOTATION


def test_a_package_publishing_its_own_submodules_is_named_as_such(
    tmp_path: Path,
) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "class Base:\n    pass\n\n\nfrom app.child import Child\n",
            "app/child.py": "from app import Base\n\n\nclass Child(Base):\n    pass\n",
        },
    )
    assert kinds_of(tmp_path)["Child"] == KIND_DOOR


def test_a_declared_registry_points_at_the_named_modules(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/settings.py": 'PLUGINS = ["app.plugin"]\n',
            "app/plugin.py": "from app.settings import PLUGINS\n",
        },
    )
    report = analyse(tmp_path)
    assert report.registries == {"app.plugin": "app.settings"}
    assert report.knots == []


def test_a_module_named_in_a_docstring_is_not_a_registry(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/settings.py": '"""See app.plugin for details."""\n',
            "app/plugin.py": "",
        },
    )
    assert analyse(tmp_path).registries == {}


def test_the_json_view_carries_the_zones_and_the_knots(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/one.py": "from app.two import B\n",
            "app/two.py": "from app.one import A\n",
        },
    )
    payload = to_dict(analyse(tmp_path))
    assert {zone["name"] for zone in payload["zones"]} >= {"app.one", "app.two"}
    assert len(payload["knots"]) == 1
    assert payload["knots"][0]["imports"][0]["file"].startswith("app/")


def test_a_knot_is_summed_up_by_the_folders_it_spans(tmp_path: Path) -> None:
    write(
        tmp_path,
        {
            "app/__init__.py": "",
            "app/http/__init__.py": "",
            "app/http/one.py": "from app.web.two import B\n",
            "app/http/three.py": "from app.http.one import A\n",
            "app/web/__init__.py": "",
            "app/web/two.py": "from app.http.three import C\n",
        },
    )
    knot = analyse(tmp_path).knots[0]
    assert len(knot.zones) == 3
    assert knot.domains == ("app.http", "app.web")
    assert "across 2: app.http, app.web" in format_text(analyse(tmp_path))
