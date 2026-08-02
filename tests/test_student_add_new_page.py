from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse
from cis.models.customuser import CustomUser

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class AddNewPageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        if _login_history_post_login is not None:
            user_logged_in.disconnect(_login_history_post_login)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if _login_history_post_login is not None:
            user_logged_in.connect(_login_history_post_login)

    @classmethod
    def setUpTestData(cls):
        ce = Group.objects.get_or_create(name='ce')[0]
        cls.admin = CustomUser.objects.create(username='a@x.com', email='a@x.com', is_active=True)
        cls.admin.set_password('pw'); cls.admin.save(); cls.admin.groups.add(ce)

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_add_new_links_to_new_importer(self):
        resp = self.client.get(reverse('cis:student_add_new'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(reverse('cis:student_import_upload'), body)
        self.assertNotIn('value="import_students"', body)
