from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user model with a required, unique email address.

    Email is the login identifier (see ACCOUNT_LOGIN_METHODS in settings), but
    ``username`` is kept as the technical USERNAME_FIELD so that
    ``createsuperuser`` and the Django admin keep working. allauth
    auto-populates ``username`` from the email/social login, so users never
    interact with it directly.
    """

    email = models.EmailField("email address", unique=True)

    def __str__(self):
        return self.email or self.username
