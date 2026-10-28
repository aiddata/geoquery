import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from analytics.models import Request


class BetaGateTests(TestCase):
    """/viz's data endpoints and the notebook exports are beta features."""

    def setUp(self):
        self.req = Request.objects.create(contact="a@example.com", status=1)
        self.urls = {
            "request-data": reverse("visualize:request-data", args=[self.req.id]),
            "explore-available": reverse("visualize:explore-available") + "?fc=1",
            "explore-data": reverse("visualize:explore-data") + "?fc=1&po=1",
            "request-export": reverse("visualize:request-export", args=[self.req.id])
            + "?format=colab",
        }

    def sign_in_beta_tester(self):
        user = get_user_model().objects.create_user(
            username="tester", email="tester@example.com"
        )
        user.user_permissions.add(Permission.objects.get(codename="beta_tester"))
        self.client.force_login(user)

    def test_rejected_without_beta_access(self):
        plain = get_user_model().objects.create_user(
            username="plain", email="plain@example.com"
        )
        for signed_in in (False, True):
            if signed_in:
                self.client.force_login(plain)
            for name, url in self.urls.items():
                with self.subTest(name=name, signed_in=signed_in):
                    self.assertEqual(self.client.get(url).status_code, 403)

    @mock.patch("visualize.views.build_request_data", return_value={})
    @mock.patch("visualize.views.build_explore_available", return_value=[])
    @mock.patch("visualize.views.build_explore_data", return_value={})
    def test_viz_endpoints_open_to_beta_testers(self, *_):
        self.sign_in_beta_tester()

        for name in ("request-data", "explore-available", "explore-data"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.urls[name]).status_code, 200)

    @override_settings(DOWNLOAD_BASE_URL="http://dl.test")
    @mock.patch("visualize.views.GistExporter")
    def test_notebook_export_open_to_beta_testers(self, exporter):
        exporter.return_value.export.return_value = "https://colab.test/x"
        self.sign_in_beta_tester()

        response = self.client.get(self.urls["request-export"])

        self.assertEqual(response.status_code, 302)

    def test_missing_request_is_still_gated_first(self):
        url = reverse("visualize:request-data", args=[uuid.uuid4()])

        self.assertEqual(self.client.get(url).status_code, 403)
