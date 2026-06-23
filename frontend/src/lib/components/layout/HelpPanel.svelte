<script lang="ts">
	import { Separator } from '$lib/components/ui/separator';
	import { parseFaq } from '$lib/utils/parseFaq';
	import rawFaq from '../../../../docs/faq.md?raw';

	const sections = parseFaq(rawFaq);
</script>

<div class="space-y-6 p-4">
	<section>
		<h3 class="font-semibold">Frequently Asked Questions</h3>
		<p class="mt-1 text-xs text-muted-foreground">
			See the full <a
				href="https://aiddata.github.io/geoquery/faq/"
				target="_blank"
				rel="noopener noreferrer"
				class="text-primary underline">FAQ page in the docs</a
			> for more detail.
		</p>
	</section>

	{#each sections as section, si}
		{#if si > 0}
			<Separator />
		{/if}
		<section>
			<h4 class="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
				{section.title}
			</h4>
			<div class="space-y-4">
				{#each section.entries as entry, ei}
					{#if ei > 0}
						<Separator />
					{/if}
					<div>
						<p class="mb-1 text-sm font-semibold">{entry.question}</p>
						<div class="text-sm text-muted-foreground [&_a]:text-primary [&_a]:underline [&_ul]:mt-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-1">
							{@html entry.answerHtml}
						</div>
					</div>
				{/each}
			</div>
		</section>
	{/each}
</div>
