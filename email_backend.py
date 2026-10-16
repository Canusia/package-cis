from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from cis.models.customuser import CustomUser
from django.contrib.auth.hashers import check_password

# from cas.backends import CASBackend, _verify

class EmailAuthBackend(ModelBackend):
    """Password login by email, or by username when no email matches.

    PT-40 (package-cis#77): this must be the only backend that checks
    passwords. Django's plain ``ModelBackend`` has to be absent from the
    tenant's AUTHENTICATION_BACKENDS (system check cis.W006): a locked account
    refused here would otherwise fall through to it and sign in on
    username + password, bypassing the lockout. Covering the username lookup
    here keeps /ce/ldap/ (raw, non-email usernames) working -- and counted.
    """

    @staticmethod
    def _find_user(username):
        if not username:
            return None
        try:
            return CustomUser.objects.get(email__iexact=username)
        except CustomUser.DoesNotExist:
            pass
        except CustomUser.MultipleObjectsReturned:
            # Several accounts share this email (case-insensitively). Fall
            # through to the exact username match, which is unique -- the
            # plain ModelBackend used to sign these accounts in that way.
            pass
        try:
            return CustomUser.objects.get(username=username)
        except CustomUser.DoesNotExist:
            return None

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = self._find_user(username)
        except Exception:
            return None
        if user is None:
            # Hash anyway, as ModelBackend does, so an unknown account does not
            # answer measurably faster than a known one.
            CustomUser().set_password(password)
            return None

        # PT-40: hold the row lock for the whole check so parallel attempts
        # are counted one at a time -- otherwise N concurrent guesses all read
        # the same counter and all get a password check before any locks.
        with transaction.atomic():
            user = CustomUser.objects.select_for_update().get(pk=user.pk)

            # A locked account never authenticates (even with the right
            # password) until staff unlock it, the user resets their password
            # through the emailed link, or the lock times out when
            # settings.ACCOUNT_LOCKOUT_MINUTES is set.
            if user.account_locked:
                if user.is_lock_active:
                    return None
                # The lock has timed out: start over with a clean counter.
                user.unlock()

            if user.check_password(password):
                user.reset_failed_login()
                return user

            # Wrong password: count it (and lock at the threshold).
            user.register_failed_login()
            return None


class CISCASBackend():
    """
    CAS authentication backend
    """

    supports_object_permissions = False
    supports_inactive_user = False

    def authenticate(self, request, ticket, service):
        """
        Verifies CAS ticket and gets or creates User object
        NB: Use of PT to identify proxy
        """

        User = get_user_model()
        username = _verify(ticket, service)

        if not username:
            return None

        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:

            # user will have an "unusable" password
            if settings.CAS_AUTO_CREATE_USER:
                user = User.objects.create_user(username, '')
                user.save()
            else:
                user = None
        return user

    def get_user(self, user_id):
        """
        Retrieve the user's entry in the User model if it exists
        """

        User = get_user_model()

        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None