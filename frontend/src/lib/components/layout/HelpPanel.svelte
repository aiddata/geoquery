<script lang="ts">
	import { Separator } from '$lib/components/ui/separator';

	const faqs = [
		{
			question: 'Do you have tutorials, videos, or additional resources where I can learn more?',
			answer:
				'Yes, check out <a href="https://www.aiddata.org/geoquery" class="text-primary underline">aiddata.org/geo</a> for a range of tutorial videos, research applications, and more.'
		},
		{
			question: 'How can I contact you for help or with questions I have?',
			answer:
				'Please email us at <a href="mailto:geo@aiddata.wm.edu" class="text-primary underline">geo@aiddata.wm.edu</a>'
		},
		// {
		// 	question: 'Can I request data extracts using my own boundary files?',
		// 	answer:
		// 		'You can request an extract with your own boundary file using the form found <a href="https://www.aiddata.org/geoquery/custom-requests" class="text-primary underline">HERE</a>.'
		// },
		{
			question: 'Where can I go to provide feedback or request new datasets?',
			answer:
				'To get in touch with our team, please email us at <a href="mailto:geo@aiddata.wm.edu" class="text-primary underline">geo@aiddata.wm.edu</a>'
		},
		{
			question: 'Can I select data for multiple boundaries?',
			answer:
				'Yes, you can select as many entire boundaries at a time as you like (e.g., Ghana ADM1, Ghana ADM2, Tanzania ADM1), but individual feature selection is only available when using a single boundary (e.g., Ghana ADM1).'
		},
		{
			question: 'What format will I receive data in?',
			answer:
				'We will email you a CSV for use in common programs (Excel, STATA, SPSS, etc), shape boundary information if you prefer use in GIS programs, and a PDF metadata/documentation file.'
		},
		{
			question: 'How do I cite data I receive from this tool?',
			answer:
				'You should cite both the individual data products you receive (details are provided in the metadata) as well as this tool: Goodman, S., BenYishay, A., Lv, Z., &amp; Runfola, D. (2019). GeoQuery: Integrating HPC systems and public web-based geospatial data tools. <em>Computers &amp; Geosciences</em>, 122, 103-112.'
		},
		{
			question: 'Do I need to cite individual datasets?',
			answer:
				'Yes. The documentation provided with your results will include citation and source information for individual datasets. These should be used along with a citation for GeoQuery.'
		},
		{
			question: 'How long will it take to receive my data?',
			answer:
				'This is highly dependent on the data requested. Many requests will be nearly instantaneous due to preprocessing and data caching, however requests which require processing may take up to several hours per aid permutation request (if selection has large number of project locations).'
		},
		{
			question:
				'Do you have examples of the types of analyses that can be conducted using this data?',
			answer:
				'Yes — we provide a number of examples of reports and publications using GeoQuery <a href="https://www.aiddata.org/geoquery/research" class="text-primary underline">HERE</a>.'
		},
		{
			question: 'Do you conduct research using this information?',
			answer:
				'Yes, we work with a wide range of organizations to analyze spatial information. Many examples can be seen <a href="https://www.aiddata.org/geoquery/research" class="text-primary underline">HERE</a>. You can also contact us at <a href="mailto:geo@aiddata.wm.edu" class="text-primary underline">geo@aiddata.wm.edu</a> to learn more.'
		},
		{
			question: 'Can I edit/update/resubmit previous requests?',
			answer:
				'You cannot modify previous requests. However, you can input multiple requests into the system, and requests you previously made will be cached (and thus will not need to be processed again, and be returned to you quicker).'
		},
		{
			question:
				'Where can I find more details on the extract methods used (e.g., mean, sum, count, as well as aid data extractions)?',
			answer:
				'You can read our paper <a href="https://www.sciencedirect.com/science/article/pii/S0098300418305326" class="text-primary underline">HERE</a> or visit <a href="https://www.aiddata.org/geoquery" class="text-primary underline">aiddata.org/geoquery</a> for links to our code and additional resources and documentation.'
		}
	];
</script>

<div class="space-y-4 p-4">
	<section>
		<h3 class="mb-2 font-semibold">Frequently Asked Questions</h3>
	</section>

	{#each faqs as faq, i}
		{#if i > 0}
			<Separator />
		{/if}
		<section>
			<h4 class="mb-1 text-sm font-semibold">{faq.question}</h4>
			<p class="text-sm text-muted-foreground">{@html faq.answer}</p>
		</section>
	{/each}
</div>
