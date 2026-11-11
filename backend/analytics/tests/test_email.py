from unittest import mock

from django.test import SimpleTestCase

from analytics.management.commands.manage_user_requests import _notify_user
from analytics.tasks.email import GeoEmail, plain_and_html


class PlainAndHtmlTests(SimpleTestCase):
    def test_bold_marker_is_dropped_from_plain_and_bolded_in_html(self):
        plain, html = plain_and_html("\nCite **both\ntools** & <data>.\n")
        self.assertEqual(plain, "\nCite both\ntools & <data>.\n")
        self.assertIn("<p>Cite <strong>both tools</strong>", html)
        self.assertIn("&amp; &lt;data&gt;", html)
        self.assertNotIn("**", html)

    def test_wrapped_lines_join_and_indented_lines_and_paragraphs_stay(self):
        _, html = plain_and_html("One\ntwo.\n\nSign,\n\tTeam\n    Ref\n")
        self.assertIn("<p>One two.</p>\n<p>Sign,<br>\n&nbsp;&nbsp;&nbsp;&nbsp;Team<br>\n", html)
        self.assertIn("&nbsp;&nbsp;&nbsp;&nbsp;Ref</p>", html)

    def test_urls_are_linked_and_tabs_indent(self):
        _, html = plain_and_html("See:\n\thttps://x.org/requests/a?b=1&c=2\n")
        self.assertIn(
            '&nbsp;&nbsp;&nbsp;&nbsp;<a href="https://x.org/requests/a?b=1&amp;c=2">'
            "https://x.org/requests/a?b=1&amp;c=2</a>",
            html,
        )


class BuildMessageTests(SimpleTestCase):
    def test_html_goes_last_as_an_alternative(self):
        msg = GeoEmail.build_message("a@b.org", "S", "plain body", "r@b.org", html="<b>x</b>")
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        parts = msg.get_payload()
        self.assertEqual([p.get_content_type() for p in parts], ["text/plain", "text/html"])
        self.assertEqual(parts[0].get_payload(decode=True).decode(), "plain body")

    def test_without_html_the_message_is_unchanged(self):
        msg = GeoEmail.build_message("a@b.org", "S", "plain body", "r@b.org")
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        self.assertEqual([p.get_content_type() for p in msg.get_payload()], ["text/plain"])


class CompletedEmailTests(SimpleTestCase):
    def test_completed_email_bolds_the_citation_reminder(self):
        with mock.patch.object(GeoEmail, "send_email", return_value=(1, None, None)) as send:
            _notify_user("abcdef1234", "u@x.org", 1, "https://dl.example", "https://app.example")
        _, subject, plain, = send.call_args.args[:3]
        html = send.call_args.kwargs["html"]
        self.assertNotIn("**", plain)
        self.assertIn("Don't forget to cite both AidData's GeoQuery", plain)
        self.assertIn("<strong>Don't forget to cite both AidData's GeoQuery tool", html)
        self.assertIn("each dataset you selected within GeoQuery.</strong>", html)
        self.assertIn('<a href="https://dl.example/requests/abcdef1234/abcdef1234.zip">', html)
