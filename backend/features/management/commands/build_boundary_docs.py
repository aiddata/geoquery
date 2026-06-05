from django.core.management.base import BaseCommand

from features.tasks.create_docs import build_boundary_docs


class Command(BaseCommand):
    help = "Generate Markdown documentation pages for all public boundary collections."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include non-public and inactive feature collections",
        )

    def handle(self, *args, **options):
        public_only = not options["all"]
        self.stdout.write("Building boundary documentation...")
        result = build_boundary_docs(public_only=public_only)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {len(result['pages'])} boundary pages + index → {result['index']}"
            )
        )