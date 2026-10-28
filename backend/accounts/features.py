"""Beta feature gate.

A short allowlist of users -- anyone holding ``accounts.beta_tester``, granted
per user or through a group in the Django admin, plus superusers implicitly --
gets every feature in ``BETA_FEATURES``. Everyone else gets none of them.

Release a feature to everyone by deleting it from ``BETA_FEATURES``: its
``has_feature`` checks then pass for every caller, including anonymous ones,
and the frontend follows because it reads the set from ``/api/config/``. The
checks and the name constant can be removed afterwards at leisure.

Refer to features through the constants below rather than bare strings, so a
typo is a NameError instead of a gate that silently lets everyone through.
"""

BETA_TESTER_PERMISSION = "accounts.beta_tester"

BROWSE_BOUNDARIES = "browse_boundaries"
CUSTOM_BOUNDARIES = "custom_boundaries"
NOTEBOOK_EXPORT = "notebook_export"
VISUALIZE = "visualize"

BETA_FEATURES = frozenset(
    {BROWSE_BOUNDARIES, CUSTOM_BOUNDARIES, NOTEBOOK_EXPORT, VISUALIZE}
)


def is_beta_tester(user) -> bool:
    return bool(user and user.has_perm(BETA_TESTER_PERMISSION))


def has_feature(user, feature: str) -> bool:
    """Whether ``user`` (which may be anonymous or None) may use ``feature``."""
    return feature not in BETA_FEATURES or is_beta_tester(user)
