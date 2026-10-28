"""Signup form extension (``ACCOUNT_SIGNUP_FORM_CLASS``).

allauth mixes this class into the base of both its signup forms, including
the headless provider-signup input, so its fields are accepted by
``POST /_allauth/browser/v1/auth/provider/signup``. Only provider signup
populates it: local (email+password) signup is closed in ``AccountAdapter``.

This module must not import ``allauth.account.forms`` -- allauth imports it
while building that module.
"""

from django import forms


class SignupForm(forms.Form):
    # Provider addresses the user chose to keep, in addition to ``email`` (the
    # primary). Anything left out is never stored, so it is never used to claim
    # requests. See ``SocialAccountAdapter.save_user``.
    emails = forms.MultipleChoiceField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The socialaccount form sets ``sociallogin`` before calling up the
        # chain; the local signup form has none.
        sociallogin = getattr(self, "sociallogin", None)
        addresses = sociallogin.email_addresses if sociallogin else []
        self.fields["emails"].choices = [(a.email, a.email) for a in addresses]

    def signup(self, request, user):
        """Required by allauth; the selection is applied in ``save_user``."""
