"""Regression contracts for KLayout 0.30 Python/Qt binding edge cases."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "pymacros/klayout_connectivity/plugin.py"


def _tree() -> ast.Module:
    return ast.parse(PLUGIN.read_text(encoding="utf-8"), filename=str(PLUGIN))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_qtimers_use_live_application_main_window_as_parent():
    """pya.MainWindow.instance() is not available in KLayout 0.30.6."""
    timer_calls = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "pya.QTimer"
    ]

    assert len(timer_calls) == 1
    assert all(call.args for call in timer_calls)
    assert {
        ast.unparse(call.args[0]) for call in timer_calls
    } == {"pya.Application.instance().main_window()"}


def test_cross_probe_guards_missing_instance_handle_before_comparison():
    """Never compare KLayout's live Instance with a null direct-reference."""
    function = _function(_tree(), "_cross_probe_finding_targets")

    null_guards = []
    for node in ast.walk(function):
        if not isinstance(node, ast.If):
            continue
        has_null_check = any(
            isinstance(part, ast.Compare)
            and isinstance(part.left, ast.Name)
            and part.left.id == "info_inst"
            and any(isinstance(op, ast.Is) for op in part.ops)
            and any(
                isinstance(comparator, ast.Constant) and comparator.value is None
                for comparator in part.comparators
            )
            for part in ast.walk(node.test)
        )
        if has_null_check and any(isinstance(stmt, ast.Continue) for stmt in node.body):
            null_guards.append(node)

    guarded_comparisons = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Try):
            continue
        compares_live_instance = any(
            isinstance(part, ast.Compare)
            and ast.unparse(part.left) == "info_inst"
            and any(isinstance(op, ast.Eq) for op in part.ops)
            and any(ast.unparse(item) == "inst" for item in part.comparators)
            for part in ast.walk(node)
        )
        catches_runtime_error = any(
            handler.type is not None and ast.unparse(handler.type) == "RuntimeError"
            for handler in node.handlers
        )
        if compares_live_instance and catches_runtime_error:
            guarded_comparisons.append(node)

    assert null_guards, "missing info.inst handle must be skipped"
    assert guarded_comparisons, "KLayout direct-reference equality must catch RuntimeError"
    assert min(node.lineno for node in null_guards) < min(
        node.lineno for node in guarded_comparisons
    )
