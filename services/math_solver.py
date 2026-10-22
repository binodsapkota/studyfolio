from __future__ import annotations

import re

import sympy as sp
from sympy.core.function import AppliedUndef, FunctionClass
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_ALLOWED_TEXT = re.compile(r"[0-9A-Za-z_+\-*/^().,=\s]+")
_BANNED = re.compile(r"__|import|exec|eval|open|lambda|os\.|sys\.|subprocess", re.IGNORECASE)

_LOCALS = {
    "simplify": sp.simplify,
    "solve": sp.solve,
    "diff": sp.diff,
    "integrate": sp.integrate,
    "limit": sp.limit,
    "N": sp.N,
    "Eq": sp.Eq,
    "sqrt": sp.sqrt,
    "log": sp.log,
    "ln": sp.log,
    "exp": sp.exp,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "pi": sp.pi,
    "E": sp.E,
    "Abs": sp.Abs,
    "factorial": sp.factorial,
    "oo": sp.oo,
}
_ALLOWED_FUNCTIONS = set(_LOCALS)


class MathCheckError(ValueError):
    """The expression is empty, unsafe, or not valid SymPy."""


def evaluate_expression(expression: str) -> str:
    text = expression.strip()
    if not text:
        raise MathCheckError("Empty expression.")
    if len(text) > 500:
        raise MathCheckError("Expression is too long.")
    if _BANNED.search(text) or not _ALLOWED_TEXT.fullmatch(text):
        raise MathCheckError("Expression uses a disallowed operation.")
    transformations = standard_transformations + (
        convert_xor,
        implicit_multiplication_application,
    )
    try:
        parsed = parse_expr(
            text,
            local_dict=_LOCALS,
            transformations=transformations,
            evaluate=True,
        )
    except Exception as exc:
        raise MathCheckError(f"Could not check `{text}`: {exc}") from exc
    _assert_safe(parsed)
    return str(parsed)


def _assert_safe(node: object) -> None:
    if isinstance(node, (list, tuple, set)):
        for item in node:
            _assert_safe(item)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            _assert_safe(key)
            _assert_safe(value)
        return
    if not isinstance(node, sp.Basic):
        return
    function = node.func
    name = getattr(function, "__name__", "")
    if isinstance(function, FunctionClass) and name and name not in _ALLOWED_FUNCTIONS:
        if function in (sp.Add, sp.Mul, sp.Pow, sp.Symbol, sp.Integer, sp.Float, sp.Rational):
            pass
        elif isinstance(node, AppliedUndef):
            raise MathCheckError(f"Function '{name}' is not allowed.")
        elif name not in {"Add", "Mul", "Pow", "Symbol", "Integer", "Float", "Rational", "Equality", "Tuple"}:
            # SymPy wraps results in its own classes. Allow arithmetic and the whitelist only.
            if name[:1].islower() or name not in {
                "Add",
                "Mul",
                "Pow",
                "Equality",
                "Relational",
                "StrictLessThan",
                "LessThan",
                "GreaterThan",
                "StrictGreaterThan",
                "Tuple",
                "FiniteSet",
                "Piecewise",
                "NaN",
                "Infinity",
                "NegativeInfinity",
                "Exp1",
                "Pi",
                "Integer",
                "Float",
                "Rational",
                "Symbol",
                "Zero",
                "One",
                "NegativeOne",
                "Half",
                "ComplexInfinity",
                "AccumBounds",
                "Order",
            }:
                if name not in _ALLOWED_FUNCTIONS and name not in {"re", "im"}:
                    # Derivative, Integral, and solved equations use Pascal-case SymPy types.
                    if not name[:1].isupper():
                        raise MathCheckError(f"Function '{name}' is not allowed.")
    for arg in getattr(node, "args", ()):
        _assert_safe(arg)
