import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = {"carla", "fastapi", "sqlalchemy", "traci", "PySide6"}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", maxsplit=1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", maxsplit=1)[0])
    return imported


def test_domain_and_ports_do_not_import_infrastructure_sdks() -> None:
    roots = [
        REPOSITORY_ROOT / "src" / "trafficverse" / "domain",
        REPOSITORY_ROOT / "src" / "trafficverse" / "ports",
    ]
    violations: dict[str, list[str]] = {}
    for root in roots:
        for path in root.rglob("*.py"):
            forbidden = sorted(_top_level_imports(path) & FORBIDDEN)
            if forbidden:
                violations[str(path.relative_to(REPOSITORY_ROOT))] = forbidden
    assert violations == {}


def test_traci_sdk_boundary_is_confined_to_sumo_adapter() -> None:
    source_root = REPOSITORY_ROOT / "src" / "trafficverse"
    violations: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        if "adapters/sumo" in path.as_posix():
            continue
        forbidden = sorted(_top_level_imports(path) & {"sumolib", "traci"})
        if forbidden:
            violations[str(path.relative_to(REPOSITORY_ROOT))] = forbidden
    assert violations == {}


def test_removed_carla_sdk_is_not_imported_anywhere() -> None:
    source_root = REPOSITORY_ROOT / "src" / "trafficverse"
    violations: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        forbidden = sorted(_top_level_imports(path) & {"carla"})
        if forbidden:
            violations[str(path.relative_to(REPOSITORY_ROOT))] = forbidden
    assert violations == {}


def test_removed_carla_adapter_is_not_referenced_anywhere() -> None:
    source_root = REPOSITORY_ROOT / "src" / "trafficverse"
    violations: dict[str, list[str]] = {}
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        modules.extend(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        forbidden = sorted(
            module for module in modules if module.startswith("trafficverse.adapters.carla")
        )
        if forbidden:
            violations[str(path.relative_to(REPOSITORY_ROOT))] = forbidden
    assert violations == {}
