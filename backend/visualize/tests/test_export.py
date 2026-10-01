import ast
import json
from unittest import mock

from django.test import SimpleTestCase

from visualize import export
from visualize.export import GistExporter

REQUEST_ID = "8c0f6f0e-2f4d-4f6e-9a3c-0d1e2f3a4b5c"
DOWNLOAD_URL = f"https://example.org/requests/{REQUEST_ID}/{REQUEST_ID}.zip"

COLAB_INJECTION = (
    'x"]},{"cell_type":"code","source":["!id"]},{"cell_type":"markdown","source":["'
)
MARIMO_INJECTION = '""");import os;os.system("id");mo.md("""'

HOSTILE_NAMES = [
    'say "hi"',
    "back\\slash",
    "two\nlines",
    COLAB_INJECTION,
    MARIMO_INJECTION,
    "{{DOWNLOAD_URL}}",
    "[click](https://evil.example) <img src=x onerror=alert(1)>",
]


def _exporter(name):
    return GistExporter(REQUEST_ID, name, DOWNLOAD_URL)


class ColabRenderTests(SimpleTestCase):
    def test_hostile_names_keep_notebook_structure(self):
        baseline = json.loads(_exporter("plain")._render_colab())
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                notebook = json.loads(_exporter(name)._render_colab())
                self.assertEqual(
                    [c["cell_type"] for c in notebook["cells"]],
                    [c["cell_type"] for c in baseline["cells"]],
                )

    def test_name_stays_inside_the_title_line(self):
        notebook = json.loads(_exporter(COLAB_INJECTION)._render_colab())
        title = notebook["cells"][0]["source"][0]
        self.assertTrue(title.startswith("# GeoQuery Results — x"))
        self.assertEqual(title.count("\n"), 1)

    def test_markdown_syntax_is_neutralised(self):
        notebook = json.loads(_exporter("[a](http://evil) <b>")._render_colab())
        title = notebook["cells"][0]["source"][0]
        self.assertIn(r"\[a\]\(http://evil\) \<b\>", title)

    def test_placeholder_in_name_is_not_expanded(self):
        notebook = json.loads(_exporter("{{DOWNLOAD_URL}}")._render_colab())
        self.assertNotIn(DOWNLOAD_URL, notebook["cells"][0]["source"][0])

    def test_download_url_and_id_are_filled(self):
        text = _exporter("plain")._render_colab()
        self.assertIn(DOWNLOAD_URL, text)
        self.assertIn(REQUEST_ID, text)
        self.assertNotIn("{{", text)


class MarimoRenderTests(SimpleTestCase):
    def test_hostile_names_keep_program_structure(self):
        baseline = ast.parse(_exporter("plain")._render_marimo())
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                tree = ast.parse(_exporter(name)._render_marimo())
                self.assertEqual(
                    [type(n) for n in tree.body], [type(n) for n in baseline.body]
                )
                for old, new in zip(baseline.body, tree.body):
                    self.assertEqual(
                        len(getattr(old, "body", [])), len(getattr(new, "body", []))
                    )

    def test_injected_call_is_not_executable_code(self):
        tree = ast.parse(_exporter(MARIMO_INJECTION)._render_marimo())
        calls = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        self.assertNotIn("system", calls)

    def test_placeholders_are_filled(self):
        text = _exporter("plain")._render_marimo()
        self.assertIn(repr(DOWNLOAD_URL), text)
        self.assertIn(REQUEST_ID, text)
        self.assertNotIn("{{", text)


class GistPostTests(SimpleTestCase):
    def test_post_uses_a_timeout(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(
            export.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            _exporter("plain")._post_gist("token", "n.ipynb", "{}")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], export._HTTP_TIMEOUT)

    def test_unreachable_github_becomes_runtime_error(self):
        for exc in (export.urllib.error.URLError("down"), TimeoutError()):
            with self.subTest(exc=exc), mock.patch.object(
                export.urllib.request, "urlopen", side_effect=exc
            ):
                with self.assertRaises(RuntimeError):
                    _exporter("plain")._post_gist("token", "n.ipynb", "{}")
