"""HighSchool.is_cte: the Details-tab checkbox and the "Set CTE" bulk action."""
import json

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase, override_settings
from django.urls import reverse

from cis.forms.highschool import HSModelForm
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool


def _disconnect_login_signal():
    """See cis.tests.test_highschool_types — django_login_history's receiver
    crashes on the test client's missing REMOTE_ADDR."""
    receivers = list(user_logged_in.receivers)
    user_logged_in.receivers = []
    return receivers


class IsCteFieldTests(TestCase):
    def test_defaults_to_false(self):
        hs = HighSchool.objects.create(name='A HS', code='AAA01')

        self.assertFalse(hs.is_cte)

    def test_details_form_offers_and_saves_the_checkbox(self):
        hs = HighSchool.objects.create(name='A HS', code='AAA01')
        form = HSModelForm(instance=hs)
        self.assertIn('is_cte', form.fields)
        self.assertEqual(form.fields['is_cte'].label, 'Is CTE')

        data = {k: v for k, v in form.initial.items() if v is not None}
        data['is_cte'] = 'on'
        form = HSModelForm(data, instance=hs)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        hs.refresh_from_db()
        self.assertTrue(hs.is_cte)


@override_settings(TENANT_SERVICES_APP='cis.tests.fake_tenant')
class SetIsCteBulkActionTests(TestCase):
    def setUp(self):
        self._saved = _disconnect_login_signal()
        ce_group, _ = Group.objects.get_or_create(name='ce')
        self.user = CustomUser.objects.create_superuser(
            email='ce@example.com', username='ce@example.com', password='pw')
        self.user.groups.add(ce_group)
        self.client.force_login(self.user)
        self.url = reverse('cis:highschool_bulk_actions')
        self.a = HighSchool.objects.create(name='A HS', code='AAA01')
        self.b = HighSchool.objects.create(name='B HS', code='BBB01', is_cte=True)

    def tearDown(self):
        user_logged_in.receivers = self._saved

    def _post(self, data):
        return self.client.post(self.url, data)

    def test_first_post_returns_the_modal(self):
        response = self._post({'action': 'set_is_cte',
                               'ids[]': [str(self.a.pk)]})

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload['outcome'], 'modal')
        self.assertIn('name="apply" value="1"', payload['html'])
        self.assertIn('name="is_cte"', payload['html'])

    def test_marks_every_selected_school(self):
        response = self._post({'action': 'set_is_cte', 'apply': '1',
                               'ids[]': [str(self.a.pk), str(self.b.pk)],
                               'is_cte': '1'})

        self.assertEqual(json.loads(response.content)['outcome'], 'call')
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertTrue(self.a.is_cte)
        self.assertTrue(self.b.is_cte)

    def test_unmarks(self):
        self._post({'action': 'set_is_cte', 'apply': '1',
                    'ids[]': [str(self.b.pk)], 'is_cte': '0'})

        self.b.refresh_from_db()
        self.assertFalse(self.b.is_cte)

    def test_missing_or_bad_value_is_rejected_and_writes_nothing(self):
        for data in ({}, {'is_cte': 'maybe'}):
            response = self._post({'action': 'set_is_cte', 'apply': '1',
                                   'ids[]': [str(self.b.pk)], **data})

            self.assertEqual(response.status_code, 400)
            self.b.refresh_from_db()
            self.assertTrue(self.b.is_cte)

    def test_no_selection_is_rejected(self):
        response = self._post({'action': 'set_is_cte'})

        self.assertEqual(response.status_code, 400)

    def test_button_is_offered_on_the_index_page(self):
        from cis.views.highschool import HIGHSCHOOL_BULK_ACTIONS

        self.assertIn('set_is_cte', HIGHSCHOOL_BULK_ACTIONS)
