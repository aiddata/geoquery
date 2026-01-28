<script lang="ts">
	import { Separator } from '$lib/components/ui/separator';
</script>

<div class="space-y-4 p-4">
	<section>
		<h3 class="mb-2 font-semibold">Getting Started</h3>
		<p class="text-sm text-muted-foreground">
			GeoQuery allows you to access and extract geospatial data without requiring mapping software
			or coding skills.
		</p>
	</section>

	<Separator />

	<section>
		<h3 class="mb-2 font-semibold">Step 1: Select Boundary</h3>
		<p class="text-sm text-muted-foreground">
			Search for and select an administrative boundary (country, region, etc.) to define your area
			of interest.
		</p>
	</section>

	<Separator />

	<section>
		<h3 class="mb-2 font-semibold">Step 2: Customize Datasets</h3>
		<p class="text-sm text-muted-foreground">
			Browse available datasets and apply filters to customize your data request. You can select
			multiple datasets.
		</p>
	</section>

	<Separator />

	<section>
		<h3 class="mb-2 font-semibold">Step 3: Review & Submit</h3>
		<p class="text-sm text-muted-foreground">
			Review your selections, provide your email address, and submit your request. You'll receive a
			notification when your data is ready.
		</p>
	</section>

	<Separator />

	<section>
		<h3 class="mb-2 font-semibold">Need More Help?</h3>
		<p class="text-sm text-muted-foreground">
			Visit our
			<a href="https://www.aiddata.org/geoquery" class="text-primary underline">documentation</a>
			or contact
			<a href="mailto:geoquery@aiddata.org" class="text-primary underline">geoquery@aiddata.org</a>.
		</p>
	</section>
</div>
