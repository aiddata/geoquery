"""The formula port must agree with frontend/src/lib/formula.ts.

Every case here is one the TypeScript implementation also handles the same
way. They are asserted rather than eyeballed because the deep link the MCP
server hands back replays the formula in the browser: a divergence would show
the user a different map from the one the assistant described.
"""

from django.test import SimpleTestCase

from mcp_server.data.formula import (
    BinOp,
    Col,
    FormulaError,
    Num,
    evaluate_formula,
    formula_columns,
    parse_formula,
    tokenize,
)


def evaluate(source: str, feature: dict | None = None):
    return evaluate_formula(parse_formula(source), feature or {})


class TokenizeTests(SimpleTestCase):
    def test_bracketed_column_is_one_token(self):
        self.assertEqual(
            tokenize("[a.b] + [c d]"), ["[a.b]", "+", "[c d]"]
        )

    def test_whitespace_is_dropped(self):
        self.assertEqual(tokenize("  1  *  2 "), ["1", "*", "2"])

    def test_unclosed_bracket(self):
        with self.assertRaisesMessage(FormulaError, "Unclosed ["):
            tokenize("[a")

    def test_unexpected_character(self):
        with self.assertRaisesMessage(FormulaError, 'Unexpected character: "%"'):
            tokenize("1 % 2")


class ParseTests(SimpleTestCase):
    def test_precedence_binds_multiplication_tighter(self):
        self.assertEqual(
            parse_formula("1 + 2 * 3"),
            BinOp("+", Num(1.0), BinOp("*", Num(2.0), Num(3.0))),
        )

    def test_parentheses_override_precedence(self):
        self.assertEqual(
            parse_formula("(1 + 2) * 3"),
            BinOp("*", BinOp("+", Num(1.0), Num(2.0)), Num(3.0)),
        )

    def test_same_precedence_is_left_associative(self):
        self.assertEqual(
            parse_formula("1 - 2 - 3"),
            BinOp("-", BinOp("-", Num(1.0), Num(2.0)), Num(3.0)),
        )

    def test_column_reference(self):
        self.assertEqual(parse_formula("[esa.mean]"), Col("esa.mean"))

    def test_empty_formula(self):
        with self.assertRaisesMessage(FormulaError, "Empty formula"):
            parse_formula("   ")

    def test_missing_closing_paren(self):
        with self.assertRaisesMessage(FormulaError, "Expected )"):
            parse_formula("(1 + 2")

    def test_trailing_token(self):
        with self.assertRaisesMessage(FormulaError, "Unexpected token: 2"):
            parse_formula("1 2")

    def test_dangling_operator(self):
        with self.assertRaisesMessage(FormulaError, "Unexpected token: end of expression"):
            parse_formula("1 +")


class EvaluateTests(SimpleTestCase):
    def test_arithmetic(self):
        self.assertEqual(evaluate("1 + 2 * 3"), 7)
        self.assertEqual(evaluate("(1 + 2) * 3"), 9)
        self.assertEqual(evaluate("10 / 4"), 2.5)

    def test_column_difference(self):
        feature = {"esa_lc_2020.mean": 10, "esa_lc_2015.mean": 4}

        self.assertEqual(
            evaluate("[esa_lc_2020.mean] - [esa_lc_2015.mean]", feature), 6
        )

    def test_null_propagates(self):
        self.assertIsNone(evaluate("[a] + 1", {"a": None}))
        self.assertIsNone(evaluate("[a] + 1", {}))

    def test_non_numeric_value_is_null_not_an_error(self):
        self.assertIsNone(evaluate("[a] * 2", {"a": "forest"}))

    def test_division_by_zero_is_null(self):
        self.assertIsNone(evaluate("[a] / [b]", {"a": 1, "b": 0}))
        self.assertIsNone(evaluate("1 / 0"))

    def test_numeric_string_is_coerced_like_Number(self):
        self.assertEqual(evaluate("[a] + 1", {"a": "2.5"}), 3.5)

    def test_boolean_coerces_to_one_like_javascript_Number(self):
        self.assertEqual(evaluate("[a] + 1", {"a": True}), 2)


class FormulaColumnsTests(SimpleTestCase):
    def test_lists_references_in_source_order(self):
        self.assertEqual(
            formula_columns(parse_formula("[b] - [a] + [b]")), ["b", "a", "b"]
        )

    def test_literals_reference_nothing(self):
        self.assertEqual(formula_columns(parse_formula("1 + 2")), [])
