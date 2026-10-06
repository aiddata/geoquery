"""The guides directory, the index it generates, and the tool that serves it.

Plain ``SimpleTestCase``: nothing here touches the database. The loader is
pointed at a temporary directory rather than at the real ``guides/``, so these
tests do not change meaning when a guide is added or edited -- except
``InstalledGuidesTests``, which deliberately checks the shipped files.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from mcp_server.data import guides as guides_module
from mcp_server.data.guides import (
    Guide,
    available_guides,
    guides_index,
    load_guide,
)
from mcp_server.data.selection import SelectionError

GUIDE = """\
---
name: style_guide
title: A style guide
description: How to build a page.
when: before you build an artifact
---

# A style guide

Use sentence case.
"""


class GuideDirectoryTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patcher = mock.patch.object(guides_module, "GUIDES_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        guides_index.cache_clear()
        self.addCleanup(guides_index.cache_clear)

    def write(self, filename: str, text: str) -> None:
        (self.dir / filename).write_text(text, encoding="utf-8")

    def test_frontmatter_is_parsed_and_kept_out_of_the_body(self):
        self.write("style_guide.md", GUIDE)

        guide = load_guide("style_guide")

        self.assertEqual(guide.title, "A style guide")
        self.assertEqual(guide.when, "before you build an artifact")
        self.assertTrue(guide.body.startswith("# A style guide"))
        # The model must not be handed the YAML header as if it were content.
        self.assertNotIn("---", guide.body)
        self.assertNotIn("description:", guide.body)

    def test_a_guide_without_frontmatter_still_loads(self):
        """A half-written guide must not take the server down at startup."""
        self.write("bare.md", "# Bare\n\nStill useful.\n")

        guide = load_guide("bare")

        self.assertEqual(guide.name, "bare")
        self.assertEqual(guide.title, "bare")
        self.assertIn("Still useful.", guide.body)

    def test_malformed_frontmatter_is_treated_as_body(self):
        self.write("broken.md", "---\n: : not yaml : :\n---\n\n# Broken\n")

        guide = load_guide("broken")

        self.assertEqual(guide.name, "broken")
        self.assertIn("# Broken", guide.body)

    def test_an_unknown_name_names_the_ones_that_exist(self):
        self.write("style_guide.md", GUIDE)

        with self.assertRaises(SelectionError) as caught:
            load_guide("styleguide")

        self.assertIn("style_guide", str(caught.exception))

    def test_guides_are_listed_by_name(self):
        self.write("zebra.md", "# Z\n")
        self.write("alpha.md", "# A\n")

        self.assertEqual([g.name for g in available_guides()], ["alpha", "zebra"])

    def test_the_index_carries_each_guide_s_trigger(self):
        self.write("style_guide.md", GUIDE)

        index = guides_index()

        self.assertIn("get_guide", index)
        self.assertIn("style_guide", index)
        self.assertIn("before you build an artifact", index)

    def test_an_empty_directory_produces_no_index(self):
        self.assertEqual(guides_index(), "")

    def test_a_missing_directory_produces_no_index(self):
        with mock.patch.object(guides_module, "GUIDES_DIR", self.dir / "nope"):
            self.assertEqual(available_guides(), [])


class InstalledGuidesTests(SimpleTestCase):
    """The guides actually shipped in the package.

    A guide with no frontmatter loads fine but advertises nothing, so it would
    silently never be read. That is the failure this guards.
    """

    def test_every_shipped_guide_advertises_itself(self):
        installed = available_guides()

        self.assertTrue(installed, "no guides found in mcp_server/guides/")
        for guide in installed:
            self.assertTrue(guide.description, f"{guide.name} has no description")
            self.assertNotEqual(
                guide.when, "when it is relevant", f"{guide.name} has no `when`"
            )
            self.assertTrue(guide.body.strip(), f"{guide.name} has no body")

    def test_the_style_guide_is_installed(self):
        self.assertIn("style_guide", {g.name for g in available_guides()})


class GuideTriggerTests(SimpleTestCase):
    def test_the_trigger_reads_as_a_sentence(self):
        guide = Guide(
            name="style_guide",
            title="t",
            description="d",
            when="before you build an artifact",
            body="b",
        )

        self.assertEqual(
            guide.trigger, "    style_guide -- read it before you build an artifact"
        )
