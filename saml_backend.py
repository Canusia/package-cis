import re, logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import FieldDoesNotExist

from cis.campus_context import current_campus_or_none, is_multi_campus

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
        except Exception as e:
            logger.error(e)
            logger.error(username)
            return None

        if is_multi_campus():
            return self._campus_checked(request, idp, user)
        return user

    def _campus_checked(self, request, idp, user):
        """Multi-campus sign-in through an IdP (MC-15, #39).

        An IdP signs users in only on the hosts of the campuses it is mapped
        to, and a user with no campus yet gets those campuses, so nobody
        signed in through SAML is left without one. Existing campus
        assignments are never overwritten.
        """
        campuses = list(idp.campuses.order_by('name'))
        serving = getattr(request, 'campus', None) or current_campus_or_none()
        if not campuses or serving not in campuses:
            logger.warning(
                'SAML IdP %s is not mapped to campus %s; login refused', idp, serving)
            return None

        if not user.process_campuses.exists():
            user.set_process_campuses(campuses)
            user.campus = dict(user.campus or {}, default_campus=str(serving.id))
            user.save(update_fields=['campus'])
        return user