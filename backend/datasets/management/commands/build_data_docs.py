from pathlib import Path

from django.core.management.base import BaseCommand

from datasets.docs.build import build_bundle, build_data_docs


class Command(BaseCommand):
    help = (
        "Generate the data documentation pages. With --out, write them into a directory "
        "(for a local docs preview); otherwise write the bundle the docs site downloads."
    )

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group()
        target.add_argument("--out", help="Directory to write datasets/ and boundaries/ into")
        target.add_argument("--bundle", help="Bundle path (default: settings.DATA_DOCS_BUNDLE)")

    def handle(self, *args, **options):
        if options["out"]:
            manifest = build_data_docs(Path(options["out"]))
            where = options["out"]
        else:
            manifest = build_bundle(options["bundle"])
            where = options["bundle"] or "settings.DATA_DOCS_BUNDLE"
        self.stdout.write(self.style.SUCCESS(
            f"{manifest['datasets']} dataset pages, {manifest['boundary_pages']} boundary pages "
            f"({manifest['collections']} collections) -> {where}"
        ))
