from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.conf import settings
from cis.models.customuser import CustomUser
from django.contrib.auth.hashers import check_password

# from cas.backends import CASBackend, _verify

class EmailAuthBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None):
        try:
            user = CustomUser.objects.get(email__iexact=username)
        except CustomUser.DoesNotExist:
            return None
        except Exception:
            return None

        # PT-40: a locked account never authenticates (even with the right
        # password) until staff unlock it.
        if user.account_locked:
            return None

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