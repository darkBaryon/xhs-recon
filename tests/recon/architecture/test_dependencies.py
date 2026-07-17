import ast
from pathlib import Path

import pytest

ROOT = Path("src/recon")


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((0, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append((node.level, node.module))
    return names


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_core_layers_do_not_import_outer_or_legacy_modules(layer):
    forbidden = (
        "src.models",
        "src.core",
        "src.adapters",
        "src.pipelines",
        "src.recon.platforms",
        "src.recon.infrastructure",
        "src.recon.entrypoints",
    )
    violations = []
    for path in (ROOT / layer).rglob("*.py"):
        for level, name in _imports(path):
            if name.startswith(forbidden):
                violations.append(f"{path}: {name}")
            if level and name.split(".", 1)[0] in {"platforms", "infrastructure", "entrypoints"}:
                violations.append(f"{path}: relative import {'.' * level}{name}")
    assert violations == []


def test_first_class_use_cases_do_not_import_each_other():
    violations = []
    use_cases = ROOT / "application"
    features = ("account", "search", "watchlist", "backfill")
    for feature in features:
        for path in (use_cases / feature).rglob("*.py"):
            for _level, name in _imports(path):
                if any(other in name.split(".") for other in features if other != feature):
                    violations.append(f"{path}: {name}")
    assert violations == []


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        (
            "platforms",
            (
                "src.models",
                "src.core",
                "src.pipelines",
                "src.recon.infrastructure",
                "src.recon.entrypoints",
            ),
        ),
        (
            "infrastructure",
            (
                "src.models",
                "src.core",
                "src.adapters",
                "src.pipelines",
                "src.recon.platforms",
                "src.recon.entrypoints",
            ),
        ),
    ],
)
def test_outer_implementation_layers_do_not_reach_across_boundaries(layer, forbidden):
    violations = []
    for path in (ROOT / layer).rglob("*.py"):
        for _level, name in _imports(path):
            if name.startswith(forbidden):
                violations.append(f"{path}: {name}")
    assert violations == []
