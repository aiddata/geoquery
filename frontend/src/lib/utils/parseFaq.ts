export interface FaqEntry {
	question: string;
	answerHtml: string;
}

export interface FaqSection {
	title: string;
	entries: FaqEntry[];
}

function mdToHtml(text: string): string {
	return (
		text
			// fenced code blocks → skip (not in our FAQ, but safe)
			// inline code
			.replace(/`([^`]+)`/g, '<code>$1</code>')
			// bold
			.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
			// links
			.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" class="text-primary underline" target="_blank" rel="noopener noreferrer">$1</a>')
	);
}

function blockToHtml(block: string): string {
	const lines = block.split('\n');
	const parts: string[] = [];
	let listItems: string[] = [];

	const flushList = () => {
		if (listItems.length) {
			parts.push(`<ul class="list-disc pl-5 space-y-1">${listItems.map((li) => `<li>${li}</li>`).join('')}</ul>`);
			listItems = [];
		}
	};

	for (const line of lines) {
		const listMatch = line.match(/^[-*]\s+(.*)/);
		if (listMatch) {
			listItems.push(mdToHtml(listMatch[1]));
		} else {
			flushList();
			const trimmed = line.trim();
			if (trimmed) parts.push(`<p>${mdToHtml(trimmed)}</p>`);
		}
	}
	flushList();

	return parts.join('');
}

export function parseFaq(markdown: string): FaqSection[] {
	const sections: FaqSection[] = [];
	let currentSection: FaqSection | null = null;
	let currentQuestion: string | null = null;
	let answerLines: string[] = [];

	const saveQuestion = () => {
		if (currentQuestion && currentSection) {
			currentSection.entries.push({
				question: currentQuestion,
				answerHtml: blockToHtml(answerLines.join('\n').trim())
			});
		}
		currentQuestion = null;
		answerLines = [];
	};

	for (const line of markdown.split('\n')) {
		if (line.startsWith('## ')) {
			saveQuestion();
			currentSection = { title: line.slice(3).trim(), entries: [] };
			sections.push(currentSection);
		} else if (line.startsWith('### ')) {
			saveQuestion();
			currentQuestion = line.slice(4).trim();
		} else if (line.trim() === '---') {
			// skip horizontal rules
		} else if (currentQuestion !== null) {
			answerLines.push(line);
		}
	}
	saveQuestion();

	return sections;
}
