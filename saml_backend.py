import re, logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import FieldDoesNotExist

UserModel = get_user_model()

logger = logging.getLogger(__name__)

class MyCE_SAMLAuthenticationBackend(ModelBackend):
    def get_username(self, idp, saml):
        """
        For users not already associated with the IdP, generate a username to either
        look up and associate, or to use when creating a new User.
        """
        # Start with either the SAML nameid, or SAML attribute mapped to nameid.
        username = idp.get_nameid(saml)

        # Make sure the username is valid for Django's User model.
        username = re.sub(r"[^a-zA-Z0-9_@\+\.]", "-", username)
        return username

    def authenticate(self, request, idp=None, saml=None):
        # The nameid (potentially mapped) to associate a User with an IdP.
        nameid = idp.get_nameid(saml)

        username = self.get_username(idp, saml)

        # A dictionary of SAML attributes, mapped to field names via IdPAttribute.
        attrs = idp.mapped_attributes(saml)
        created = False
        try:
            username_field = "username"
            if not idp.auth_case_sensitive:
                username_field += "__iexact"
            user = UserModel._default_manager.get(**{username_field: username})
            return user
        except Exception as e:
            logger.error(e)
            logger.error(username)
            return None

        return None