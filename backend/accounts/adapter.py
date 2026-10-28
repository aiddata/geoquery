import dataclasses
import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.headless.adapter import DefaultHeadlessAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from accounts.features import is_beta_tester

logger = logging.getLogger(__name__)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Socialaccount adapter that logs otherwise-swallowed OAuth errors.

    allauth catches exceptions in the OAuth2 callback and turns them into an
    opaque ``?error=unknown`` redirect, with no traceback anywhere. Log it.
    """

    def is_open_for_signup(self, request, sociallogin):
        # The default delegates to the account adapter, which returns False to
        # close email+password signup -- that would close GitHub signup too.
        return True

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
