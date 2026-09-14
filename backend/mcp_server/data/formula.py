"""Column formulas: a Python port of ``frontend/src/lib/formula.ts``.

The web app already lets a user build a derived index over the columns of a
selection (``[a] - [b]``), and the deep links the MCP server hands back carry
that formula in ``?formula=``. So the two implementations have to agree
exactly, right down to which inputs are errors: a formula the model writes
here must replay identically when the user opens the link.

Grammar: ``+ - * /`` with the usual precedence, parentheses, numeric literals,
and ``[column.name]`` references. Nulls propagate -- any null operand, or a
division by zero, yields null rather than raising, because a map with a hole
in it is the right answer for a feature with no data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class FormulaError(ValueError):
    """A formula that cannot be parsed, or that names a column not present."""


@dataclass(frozen=True)
class Num:
    val: float


@dataclass(frozen=True)
class Col:
    name: str


@dataclass(frozen=True)
class BinOp:
    op: str
    left: "Expr"
    right: "Expr"


Expr = Num | Col | BinOp

_NUMBER_CHARS = re.compile(r"[0-9.]")
_OPERATORS = ("+", "-", "*", "/", "(", ")")


def tokenize(source: str) -> list[str]:
    """Split a formula into tokens, mirroring ``tokenize`` in formula.ts.

    Bracketed column references are taken whole (including their brackets) so
    a column name may contain any character except ``]``.
    """
    tokens: list[str] = []
    i = 0
    while i < len(source):
        char = source[i]
        if char.isspace():
            i += 1
        elif char == "[":
            end = source.find("]", i)
            if end == -1:
                raise FormulaError("Unclosed [")
            tokens.append(source[i : end + 1])
            i = end + 1
        elif _NUMBER_CHARS.match(char):
            j = i
            while j < len(source) and _NUMBER_CHARS.match(source[j]):
                j += 1
            tokens.append(source[i:j])
            i = j
        elif char in _OPERATORS:
            tokens.append(char)
            i += 1
        else:
            raise FormulaError(f'Unexpected character: "{char}"')
    return tokens


class _Parser:
    """Recursive-descent parser, same three levels as the TypeScript twin."""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self) -> str | None:
        token = self.peek()
        self.pos += 1
        return token

    def parse_expr(self) -> Expr:
        left = self.parse_term()
        while self.peek() in ("+", "-"):
            op = self.consume()
            left = BinOp(op, left, self.parse_term())
        return left

    def parse_term(self) -> Expr:
        left = self.parse_factor()
        while self.peek() in ("*", "/"):
            op = self.consume()
            left = BinOp(op, left, self.parse_factor())
        return left

    def parse_factor(self) -> Expr:
        token = self.peek()
        if token == "(":
            self.consume()
            expr = self.parse_expr()
            if self.consume() != ")":
                raise FormulaError("Expected )")
            return expr
        if token is not None and token.startswith("["):
            self.consume()
            return Col(token[1:-1])
        if token is not None and _NUMBER_CHARS.match(token[0]):
            self.consume()
            try:
                return Num(float(token))
            except ValueError:
                raise FormulaError(f"Invalid number: {token}") from None
        raise FormulaError(f"Unexpected token: {token or 'end of expression'}")

    def assert_end(self) -> None:
        if self.pos < len(self.tokens):
            raise FormulaError(f"Unexpected token: {self.tokens[self.pos]}")


def parse_formula(source: str) -> Expr:
    tokens = tokenize(source.strip())
    if not tokens:
        raise FormulaError("Empty formula")
    parser = _Parser(tokens)
    expr = parser.parse_expr()
    parser.assert_end()
    return expr


def evaluate_formula(expr: Expr, feature: dict) -> float | None:
    """Evaluate against one feature's values. Null in, null out.

    A missing key, a null, or a value that is not numeric all yield ``None``,
    matching ``Number(v)``/``isNaN`` in the TypeScript version -- so a
    categorical column dragged into a formula produces empty cells rather than
    an error the user cannot act on.
    """
    if isinstance(expr, Num):
        return expr.val
    if isinstance(expr, Col):
        value = feature.get(expr.name)
        if value is None:
            return None
        try:
            # bool is deliberately left to float()'s True -> 1.0, matching
            # JavaScript's Number(true): this is a port, and a divergence
            # would make the ?formula= deep link render a different map from
            # the one the assistant just described.
            number = float(value)
        except (TypeError, ValueError):
            return None
        return None if number != number else number  # NaN check

    left = evaluate_formula(expr.left, feature)
    right = evaluate_formula(expr.right, feature)
    if left is None or right is None:
        return None
    if expr.op == "/":
        return None if right == 0 else left / right
    if expr.op == "+":
        return left + right
    if expr.op == "-":
        return left - right
    return left * right


def formula_columns(expr: Expr) -> list[str]:
    """Column names referenced by an expression, in source order."""
    if isinstance(expr, Num):
        return []
    if isinstance(expr, Col):
        return [expr.name]
    return formula_columns(expr.left) + formula_columns(expr.right)
