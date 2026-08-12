"""Map files to dotted module names relative to a project root."""
from pathlib import Path

from scopify.modules import module_name_for, package_of, top_level_package


def test_module_name_for_regular_file(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "a.py").write_text("")
    assert module_name_for(tmp_path / "pkg" / "a.py", tmp_path) == "pkg.a"


def test_module_name_for_init(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    assert module_name_for(tmp_path / "pkg" / "__init__.py", tmp_path) == "pkg"


def test_module_name_for_nested(tmp_path: Path):
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "sub" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "sub" / "b.py").write_text("")
    assert module_name_for(tmp_path / "pkg" / "sub" / "b.py", tmp_path) == "pkg.sub.b"


def test_package_of():
    assert package_of("pkg.a") == "pkg"
    assert package_of("pkg.sub.b") == "pkg.sub"
    assert package_of("pkg") == "pkg"
    assert package_of("toplevel") == "toplevel"


def test_top_level_package():
    # Top-level package is its own root.
    assert package_of("pkg") == "pkg"


def test_module_name_for_path_outside_root_returns_none(tmp_path: Path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    outside_file = other / "a.py"
    outside_file.write_text("")
    root = tmp_path / "root"
    root.mkdir()
    assert module_name_for(outside_file, root) is None


def test_module_name_for_non_python_file_returns_none(tmp_path: Path):
    (tmp_path / "notes.txt").write_text("hi")
    assert module_name_for(tmp_path / "notes.txt", tmp_path) is None


def test_module_name_for_root_level_init_returns_none(tmp_path: Path):
    # An `__init__.py` sitting directly at the analysis root has no package
    # segment left once it's dropped — there's nothing meaningful to name it.
    (tmp_path / "__init__.py").write_text("")
    assert module_name_for(tmp_path / "__init__.py", tmp_path) is None


def test_top_level_package_no_roots_uses_first_segment():
    assert top_level_package("alpha.core") == "alpha"


def test_top_level_package_with_roots_matches_longest_prefix():
    roots = ["src.pkgA", "src.pkgA.sub"]
    # The longer, more specific root must win over the shorter one.
    assert top_level_package("src.pkgA.sub.deep", roots) == "src.pkgA.sub"
    assert top_level_package("src.pkgA.other", roots) == "src.pkgA"


def test_top_level_package_with_roots_falls_back_when_no_root_matches():
    roots = ["other.pkg"]
    assert top_level_package("alpha.core", roots) == "alpha"

