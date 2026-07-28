from allauth.account.adapter import DefaultAccountAdapter


class AccountAdapter(DefaultAccountAdapter):
    """Account adapter that closes classic email+password signup.

    Social signup (GitHub) is governed by the socialaccount adapter, which
    stays open, so GitHub logins can still create accounts. Return ``True``
    here (or drop this adapter) if we later want to offer password-based
    registration.
    """

    def is_open_for_signup(self, request):
        return False
