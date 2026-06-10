// Minimal expression parser for user-defined column indices.
// Supports: +, -, *, / with standard precedence, parentheses, numeric
// literals, and column references using [column.name] bracket syntax.

export type FormulaExpr =
	| { type: 'num'; val: number }
	| { type: 'col'; name: string }
	| { type: 'binop'; op: '+' | '-' | '*' | '/'; left: FormulaExpr; right: FormulaExpr };

function tokenize(input: string): string[] {
	const tokens: string[] = [];
	let i = 0;
	while (i < input.length) {
		if (/\s/.test(input[i])) { i++; continue; }
		if (input[i] === '[') {
			const end = input.indexOf(']', i);
			if (end === -1) throw new Error('Unclosed [');
			tokens.push(input.slice(i, end + 1));
			i = end + 1;
		} else if (/[0-9.]/.test(input[i])) {
			let j = i;
			while (j < input.length && /[0-9.]/.test(input[j])) j++;
			tokens.push(input.slice(i, j));
			i = j;
		} else if (['+', '-', '*', '/', '(', ')'].includes(input[i])) {
			tokens.push(input[i]);
			i++;
		} else {
			throw new Error(`Unexpected character: "${input[i]}"`);
		}
	}
	return tokens;
}

class Parser {
	private tokens: string[];
	private pos = 0;

	constructor(tokens: string[]) { this.tokens = tokens; }

	private peek(): string | undefined { return this.tokens[this.pos]; }
	private consume(): string { return this.tokens[this.pos++]; }

	parseExpr(): FormulaExpr {
		let left = this.parseTerm();
		while (this.peek() === '+' || this.peek() === '-') {
			const op = this.consume() as '+' | '-';
			left = { type: 'binop', op, left, right: this.parseTerm() };
		}
		return left;
	}

	parseTerm(): FormulaExpr {
		let left = this.parseFactor();
		while (this.peek() === '*' || this.peek() === '/') {
			const op = this.consume() as '*' | '/';
			left = { type: 'binop', op, left, right: this.parseFactor() };
		}
		return left;
	}

	parseFactor(): FormulaExpr {
		const tok = this.peek();
		if (tok === '(') {
			this.consume();
			const expr = this.parseExpr();
			if (this.consume() !== ')') throw new Error('Expected )');
			return expr;
		}
		if (tok?.startsWith('[')) {
			this.consume();
			return { type: 'col', name: tok.slice(1, -1) };
		}
		if (tok && /^[0-9.]/.test(tok)) {
			this.consume();
			const val = parseFloat(tok);
			if (isNaN(val)) throw new Error(`Invalid number: ${tok}`);
			return { type: 'num', val };
		}
		throw new Error(`Unexpected token: ${tok ?? 'end of expression'}`);
	}

	assertEnd() {
		if (this.pos < this.tokens.length) throw new Error(`Unexpected token: ${this.tokens[this.pos]}`);
	}
}

export function parseFormula(input: string): FormulaExpr {
	const tokens = tokenize(input.trim());
	if (tokens.length === 0) throw new Error('Empty formula');
	const p = new Parser(tokens);
	const expr = p.parseExpr();
	p.assertEnd();
	return expr;
}

export function evaluateFormula(expr: FormulaExpr, feature: Record<string, unknown>): number | null {
	if (expr.type === 'num') return expr.val;
	if (expr.type === 'col') {
		const v = feature[expr.name];
		if (v === null || v === undefined) return null;
		const n = Number(v);
		return isNaN(n) ? null : n;
	}
	const l = evaluateFormula(expr.left, feature);
	const r = evaluateFormula(expr.right, feature);
	if (l === null || r === null) return null;
	if (expr.op === '/' && r === 0) return null;
	if (expr.op === '+') return l + r;
	if (expr.op === '-') return l - r;
	if (expr.op === '*') return l * r;
	return l / r;
}

export function formulaColumns(expr: FormulaExpr): string[] {
	if (expr.type === 'num') return [];
	if (expr.type === 'col') return [expr.name];
	return [...formulaColumns(expr.left), ...formulaColumns(expr.right)];
}
