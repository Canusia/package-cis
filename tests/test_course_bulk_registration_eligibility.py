from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase
from django.urls import reverse

from cis.models.customuser import CustomUser
from cis.models.course import Course, Campus, Cohort

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:
    _login_history_post_login = None


class CourseBulkRegistrationEligibilityActionTests(TestCase):
    """Covers the /ce/courses/ 'Update Registration Eligibility' bulk action
    end-to-end, mirroring the modal-then-confirm flow of the existing bulk
    actions."""

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
        cls.admin = CustomUser.objects.create(
            username='ce@x.com', email='ce@x.com', is_active=True)
        cls.admin.set_password('pw')
        cls.admin.save()
        cls.admin.groups.add(ce)

        cls.cohort = Cohort.objects.create(name='Co', designator='CO')
        cls.c1 = Course.objects.create(
            name='C1', title='One', cohort=cls.cohort,
            catalog_number='101', credit_hours=3,
            registration_eligibility=['SR'])
        cls.c2 = Course.objects.create(
            name='C2', title='Two', cohort=cls.cohort,
            catalog_number='102', credit_hours=3,
            registration_eligibility=['SR', 'JR'])
        cls.url = reverse('cis:course_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_action_registered_in_bulk_scope(self):
        from myce.component_registry.course import course_actions
        slugs = {slug for g in course_actions.for_scope('bulk').values()
                 for slug in g['actions']}
        self.assertIn('update_course_registration_eligibility', slugs)

    def test_button_reaches_the_courses_index_page(self):
        """Registration alone does not put the button on the page — it has to
        survive for_scope('bulk', user) and the table config's bulk_actions."""
        resp = self.client.get(reverse('cis:courses'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('update_course_registration_eligibility', html)
        self.assertIn('Update Registration Eligibility', html)

    def test_first_pass_returns_modal_with_every_grade_choice(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'ids[]': [str(self.c1.id), str(self.c2.id)],
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['outcome'], 'modal')
        self.assertIn('name="registration_eligibility"', body['html'])
        for code, _label in Course.GRADE_LEVEL:
            with self.subTest(code=code):
                self.assertIn(f'value="{code}"', body['html'])

    def test_confirm_replaces_eligibility_on_selected_courses(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id), str(self.c2.id)],
            'registration_eligibility': ['JR*', 'SR'],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['outcome'], 'call')

        self.c1.refresh_from_db()
        self.c2.refresh_from_db()
        self.assertEqual(list(self.c1.registration_eligibility), ['JR*', 'SR'])
        # Replaces rather than merges: c2's JR is gone, not kept alongside JR*.
        self.assertEqual(list(self.c2.registration_eligibility), ['JR*', 'SR'])

    def test_saved_value_is_a_list_not_a_joined_string(self):
        """MultiSelectField converts in pre_save, which .update() skips — a
        queryset update would store "['JR*']" and break every `f'{grade}*' in
        eligibility` membership test that reads it back."""
        self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id)],
            'registration_eligibility': ['JR*'],
        })
        self.c1.refresh_from_db()
        self.assertEqual(list(self.c1.registration_eligibility), ['JR*'])
        self.assertIn('JR*', self.c1.registration_eligibility)
        self.assertNotIn('J', self.c1.registration_eligibility)

    def test_confirm_requires_at_least_one_grade(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id)],
        })
        self.assertEqual(resp.status_code, 400)
        self.c1.refresh_from_db()
        self.assertEqual(list(self.c1.registration_eligibility), ['SR'])

    def test_confirm_rejects_a_grade_outside_the_choices(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id)],
            'registration_eligibility': ['PHD'],
        })
        self.assertEqual(resp.status_code, 400)
        self.c1.refresh_from_db()
        self.assertEqual(list(self.c1.registration_eligibility), ['SR'])

    def test_unselected_courses_are_untouched(self):
        self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'record_ids': [str(self.c1.id)],
            'registration_eligibility': ['FR*'],
        })
        self.c2.refresh_from_db()
        self.assertEqual(list(self.c2.registration_eligibility), ['SR', 'JR'])


class CourseBulkRegistrationEligibilityCampusScopeTests(TestCase):
    """A ce admin must not rewrite eligibility on another campus's course, on
    either pass — the confirm payload is re-gated because the ids the modal was
    built from are not the ids it posts back."""

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
        cls.mine = Campus.objects.create(name='Cheney', code='CHY')
        cls.theirs = Campus.objects.create(name='Spokane', code='SPK')

        cls.admin = CustomUser.objects.create(
            username='ce2@x.com', email='ce2@x.com', is_active=True)
        cls.admin.set_password('pw')
        cls.admin.campus = {'process_campus': [str(cls.mine.id)]}
        cls.admin.save()
        cls.admin.groups.add(ce)

        cls.cohort = Cohort.objects.create(name='Co', designator='CO')
        cls.own = Course.objects.create(
            name='OWN', title='Own', cohort=cls.cohort, catalog_number='201',
            credit_hours=3, campus=cls.mine, registration_eligibility=['SR'])
        cls.other = Course.objects.create(
            name='OTHER', title='Other', cohort=cls.cohort,
            catalog_number='202', credit_hours=3, campus=cls.theirs,
            registration_eligibility=['SR'])
        cls.url = reverse('cis:course_bulk_actions')

    def setUp(self):
        self.client = self.client_class(REMOTE_ADDR='127.0.0.1')
        self.client.force_login(self.admin)

    def test_modal_lists_only_processable_courses(self):
        resp = self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'ids[]': [str(self.own.id), str(self.other.id)],
        })
        html = resp.json()['html']
        self.assertIn(str(self.own.id), html)
        self.assertNotIn(str(self.other.id), html)

    def test_confirm_cannot_reach_another_campus(self):
        self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'ids[]': [str(self.own.id), str(self.other.id)],
            'record_ids': [str(self.own.id), str(self.other.id)],
            'registration_eligibility': ['FR*'],
        })
        self.own.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(list(self.own.registration_eligibility), ['FR*'])
        self.assertEqual(list(self.other.registration_eligibility), ['SR'])

    def test_confirm_without_ids_still_gates_record_ids(self):
        """The modal flow posts record_ids only; that path is gated too."""
        self.client.post(self.url, {
            'action': 'update_course_registration_eligibility',
            'action_confirmed': '1',
            'record_ids': [str(self.other.id)],
            'registration_eligibility': ['FR*'],
        })
        self.other.refresh_from_db()
        self.assertEqual(list(self.other.registration_eligibility), ['SR'])
