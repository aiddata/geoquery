"""The curation worklist: what still has no license or citation."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .factories import make_dataset, make_fc


def report(**options) -> str:
    out = StringIO()
    call_command("report_missing_attribution", stdout=out, **options)
    return out.getvalue()


class ReportMissingAttributionTests(TestCase):
    def setUp(self):
        self.complete = make_dataset(name="complete", title="Complete")
        self.no_license = make_dataset(name="no_license", license=None)
        self.no_citation = make_dataset(name="no_citation", citation=None)
        self.fc_complete = make_fc(name="fc_complete")
        self.fc_bare = make_fc(name="fc_bare", license=None, citation=None)

    def test_lists_only_records_with_a_gap(self):
        output = report()

        self.assertNotIn("complete:", output)
        self.assertNotIn("fc_complete:", output)
        self.assertIn("no_license: missing license", output)
        self.assertIn("no_citation: missing citation", output)
        self.assertIn("fc_bare: missing license, citation", output)

    def test_names_the_source_so_it_can_be_looked_up(self):
        self.assertIn("(ESA CCI)", report())

    def test_counts_the_total(self):
        self.assertIn("3 record(s) missing license or citation.", report())

    def test_inactive_records_are_excluded_by_default(self):
        make_dataset(name="draft", active=False, license=None)

        self.assertNotIn("draft:", report())
        self.assertIn("draft:", report(all=True))

    def test_public_only_narrows_to_what_users_can_actually_see(self):
        make_dataset(name="internal", public=False, license=None)

        self.assertIn("internal:", report())
        self.assertNotIn("internal:", report(public_only=True))

    def test_a_clean_catalog_says_so(self):
        from datasets.models import Dataset
        from features.models import FeatureCollection

        Dataset.objects.filter(license__isnull=True).update(license="CC BY 4.0")
        Dataset.objects.filter(citation__isnull=True).update(citation="Author (2020).")
        FeatureCollection.objects.filter(license__isnull=True).update(
            license="CC BY 4.0"
        )
        FeatureCollection.objects.filter(citation__isnull=True).update(
            citation="Author (2020)."
        )

        output = report()

        self.assertIn("0 record(s) missing license or citation.", output)
        self.assertIn("nothing missing", output)
