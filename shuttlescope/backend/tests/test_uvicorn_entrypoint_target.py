from __future__ import annotations

import ast
from pathlib import Path


MAIN = Path(__file__).resolve().parents[1] / "main.py"


def test_production_entrypoint_uses_existing_app_object_when_reload_is_off():
    src = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(src)

    found_target_assignment = False
    found_run_target = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "_uvicorn_target"
                for target in node.targets
            ):
                segment = ast.get_source_segment(src, node.value) or ""
                assert '"backend.main:app"' in segment
                assert "if _reload_enabled else app" in segment
                found_target_assignment = True

        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "_uvicorn_target"
            ):
                found_run_target = True

    assert found_target_assignment
    assert found_run_target
