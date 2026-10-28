import dataclasses
import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.utils import user_email
from allauth.headless.adapter import DefaultHeadlessAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from accounts.features import is_beta_tester

logger = logging.getLogger(__name__)

# GitHub's private commit address. It is reported as verified, but mail sent
# to it is discarded, and nobody submits requests under it.
GITHUB_NOREPLY_DOMAIN = "users.noreply.github.com"


def _is_noreply(email: str) -> bool:
    domain = email.rpartition("@")[2].lower()
    return domain == GITHUB_NOREPLY_DOMAIN or domain.endswith("." + GITHUB_NOREPLY_DOMAIN)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Socialaccount adapter that asks before importing provider emails.

    GitHub reports every address on the account, including private ones the
    user never chose to share with GeoQuery. Signup stores only addresses the
    user selects, and verified addresses claim historical requests, so the
    selection also controls which requests are linked.

    It also logs OAuth errors: allauth catches exceptions in the OAuth2
    callback and turns them into an opaque ``?error=unknown`` redirect, with no
    traceback anywhere.
    """

    def is_open_for_signup(self, request, sociallogin):
        # The default delegates to the account adapter, which returns False to
        # close email+password signup -- that would close GitHub signup too.
        return True

    def pre_social_login(self, request, sociallogin):
        # Runs after the email-authentication lookup, which may still match an
        # existing account by any provider-verified address. From here on --
        # auto-signup, the pending signup and its address picker -- only
        # verified, deliverable addresses are offered.
        sociallogin.email_addresses = [
            address
            for address in sociallogin.email_addresses
            if address.verified and not _is_noreply(address.email)
        ]
        super().pre_social_login(request, sociallogin)

    def is_auto_signup_allowed(self, request, sociallogin):
        # With more than one address, park the signup so the user can choose.
        # A single address is the one they signed in with; take it.
        return (
            super().is_auto_signup_allowed(request, sociallogin)
            and len(sociallogin.email_addresses) <= 1
        )

    def save_user(self, request, sociallogin, form=None):
        if form is not None:
            # ``email`` is the primary; ``emails`` are the extra addresses kept.
            data = form.cleaned_data
            primary = (data.get("email") or "").lower()
            chosen = {
                email.lower() for email in [primary, *data.get("emails", [])] if email
            }
            # allauth prefers the provider's primary flag over the form's
            # choice, so make the flags agree with the user.
            for address in sociallogin.email_addresses:
                address.primary = address.email.lower() == primary
        else:
            chosen = {address.email.lower() for address in sociallogin.email_addresses}
            # The profile email becomes the primary at auto-signup; drop it if
            # it was filtered out so only offered addresses are stored.
            if (user_email(sociallogin.user) or "").lower() not in chosen:
                user_email(sociallogin.user, "")
        sociallogin.email_addresses = [
            address
            for address in sociallogin.email_addresses
            if address.email.lower() in chosen
        ]
        return super().save_user(request, sociallogin, form=form)

    def on_authentication_error(
        self, request, provider, error=None, exception=None, extra_context=None
    ):
        logger.error(
            "Social authentication error: provider=%s error=%s exception=%r",
            getattr(provider, "id", provider),
            error,
            exception,
            exc_info=exception,
        )
        return super().on_authentication_error(
            request, provider, error=error, exception=exception, extra_context=extra_context
        )


class AccountAdapter(DefaultAccountAdapter):
    """Account adapter that closes classic email+password signup.

    Social signup (GitHub) is governed by the socialaccount adapter, which
    stays open, so GitHub logins can still create accounts. Return ``True``
    here (or drop this adapter) if we later want to offer password-based
    registration.
    """

    def is_open_for_signup(self, request):
        return False


class HeadlessAdapter(DefaultHeadlessAdapter):
    """Headless adapter that adds the beta-tester flag to the user payload.

    The SPA reads the user from allauth's session responses, so the flag
    reaches the frontend without a separate request. Which features are in
    beta comes from ``/api/config/``. Both are UI hints only -- every gated
    action is enforced again by the view that performs it (see
    ``accounts.features``).
    """

    def get_user_dataclass(self):
        base = super().get_user_dataclass()
        return dataclasses.make_dataclass(
            base.__name__,
            [
                (
                    "is_beta_tester",
                    bool,
                    dataclasses.field(
                        default=False,
                        metadata={
                            "description": "Whether the user may use beta features.",
                            "example": False,
                        },
                    ),
                )
            ],
            bases=(base,),
        )

    def user_as_dataclass(self, user):
        dc = super().user_as_dataclass(user)
        dc.is_beta_tester = bool(user.pk and is_beta_tester(user))
        return dc
