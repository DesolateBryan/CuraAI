"""The Dependency Rule, checked without third-party tools (import-linter covers the rest in CI).

Ring 1 may import only the standard library and itself.
Ring 2 may import only the standard library, Ring 1 and itself.
"""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "curaai"


def _imports(package: str) -> dict[str, set[str]]:
    found = {}
    for path in (SRC / package).rglob("*.py"):
        names = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
        found[path.relative_to(SRC).as_posix()] = names
    return found


def _violations(package: str, allowed_internal: tuple[str, ...]) -> list[str]:
    bad = []
    for file, names in _imports(package).items():
        for name in names:
            top = name.split(".")[0]
            if top == "curaai":
                if not name.startswith(allowed_internal):
                    bad.append(f"{file} -> {name}")
            elif top not in sys.stdlib_module_names:
                bad.append(f"{file} -> {name} (third-party)")
    return bad


def test_domain_imports_nothing_outward():
    assert _violations("domain", ("curaai.domain",)) == []


def test_application_imports_only_domain():
    assert _violations("application", ("curaai.domain", "curaai.application")) == []


def test_no_adapter_or_sdk_names_appear_in_the_inner_rings():
    forbidden = ("MockEpicAdapter", "OpenFdaAdapter", "GatewayClient", "ReviewPresenter", "FastAPI", "boto3")
    for package in ("domain", "application"):
        for path in (SRC / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            identifiers |= {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
            assert not identifiers & set(forbidden), path


def test_adapter_packages_never_import_each_other():
    packages = sorted(p.name for p in (SRC / "adapters").iterdir() if p.is_dir() and not p.name.startswith("_"))
    bad = []
    for package in packages:
        for file, names in _imports(f"adapters/{package}").items():
            for name in names:
                if name.startswith("curaai.adapters.") and name.split(".")[2] != package:
                    bad.append(f"{file} -> {name}")
    assert bad == []


def test_only_main_imports_the_vendor_sdk_and_fastapi():
    hits = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                   [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for m in mods:
                if m.split(".")[0] in ("boto3", "fastapi", "uvicorn"):
                    hits.append((path.relative_to(SRC).as_posix(), m.split(".")[0]))
    allowed = {("app/main.py", "boto3"), ("app/main.py", "uvicorn"), ("adapters/web/routers.py", "fastapi")}
    assert set(hits) <= allowed, set(hits) - allowed
