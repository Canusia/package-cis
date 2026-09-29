"""MC-10 (#34): campus_url builds links on the campus's own host."""
import uuid

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from cis.campus_context import campus_context, campus_url
from cis.models.course import Campus
from cis.models.customuser import CustomUser


def _campus(domain=None):
    site = Site.objects.create(domain=domain, name=domain) if domain else None
    return Campus.objects.create(
        name=f'C-{uuid.uuid4().hex[:6]}',
        code=f'{settings.CAMPUS_CODE_PREFIX}-{uuid.uuid4().hex[:6]}', site=site)


class CampusUrlTests(TestCase):
    def test_uses_the_campus_site(self):
        self.assertEqual(campus_url(_campus('c1.link.edu'), '/x'), 'https://c1.link.edu/x')

    def test_single_campus_falls_back_to_the_current_site(self):
        current = Site.objects.get_current().domain
        self.assertEqual(campus_url(None, '/x'), f'https://{current}/x'
                         if not current.startswith('http') else f'{current}/x')

    @override_settings(MULTI_CAMPUS=True)
    def test_multi_campus_without_a_site_raises(self):
        with self.assertRaises(ImproperlyConfigured):
            campus_url(_campus(), '/x')

    @override_settings(MULTI_CAMPUS=True)
    def test_password_reset_link_uses_the_current_campus_host(self):
        c2 = _campus('c2.link.edu')
        user = CustomUser.objects.create_user(
            username=f'u{uuid.uuid4().hex[:6]}', email=f'{uuid.uuid4().hex[:6]}@x.com',
            password='x')
        with campus_context(c2):
            self.assertTrue(user.get_password_reset_link().startswith('https://c2.link.edu/'))

    @override_settings(MULTI_CAMPUS=True)
    def test_hs_upload_review_link_uses_the_campus_host(self):
        from cis.services.hs_uploads import uploads_review_url
        c1 = _campus('c1.link.edu')
        self.assertEqual(uploads_review_url(c1),
                         'https://c1.link.edu/ce/students/support_docs/#hs_uploads')
