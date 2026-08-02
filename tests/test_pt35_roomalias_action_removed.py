"""PT-35 (Medium): the `highschoolclassoffering_roomalias` AJAX action must be
removed. It performed a CSRF-unprotected GET write to `room_alias` on
ClassSection / HighSchoolClassOffering.

After removal, hitting /ce/add_new_ajax/ with
model=courseoffering&action=highschoolclassoffering_roomalias must NOT mutate
room_alias on either model — the action no longer exists, so the dispatcher
returns its generic 'invalid action' response and the records are unchanged.

The room_alias FIELD itself is intentionally retained (edited via the normal
CSRF-protected section edit form); only the unsafe ad-hoc write ACTION is gone.

Run:
  docker exec -w /app/webapp django_web_ewu python manage.py \
    test cis.tests.test_pt35_roomalias_action_removed -v 2
"""
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

from cis.models.section import ClassSection
from cis.models.highschool import HighSchool, HighSchoolClassOffering
from cis.models.course import Cohort, Course
from cis.models.term import Term, AcademicYear

User = get_user_model()

ACTION = 'highschoolclassoffering_roomalias'
ENDPOINT = '/ce/add_new_ajax/'
ORIGINAL = 'A1'
ATTACK = 'HACK'


class PT35RoomAliasActionRemovedTests(TestCase):
    @classmethod
    def setUpClass(cls):
        # django_login_history's post_login signal handler blows up in tests
        # because the request has no usable IP. Disconnect for the duration
        # of this test case.
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
        Group.objects.get_or_create(name='ce')

        cls.staff = User.objects.create_user(
            username='staff_pt35', email='staff_pt35@example.com',
            password='x', first_name='S', last_name='T', is_staff=True,
        )
        cls.staff.groups.add(Group.objects.get(name='ce'))

        cls.cohort = Cohort.objects.create(name='PT35Co', designator='P35')
        cls.course = Course.objects.create(
            name='PT35Course', title='PT35', cohort=cls.cohort,
            catalog_number='350', credit_hours=3,
        )
        cls.academic_year = AcademicYear.objects.create(name='PT35 AY')
        cls.term = Term.objects.create(
            academic_year=cls.academic_year, code='PT35T', label='PT35 Term',
        )

        cls.section = ClassSection.objects.create(
            course=cls.course, term=cls.term, room_alias=ORIGINAL,
            class_number='PT35-001', section_number='001',
        )

        cls.hs = HighSchool.objects.create(name='PT35 HS')
        cls.offering = HighSchoolClassOffering.objects.create(
            highschool=cls.hs, class_section=cls.section, room_alias=ORIGINAL,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def _params(self, target_id):
        return {
            'model': 'courseoffering',
            'action': ACTION,
            'id': str(target_id),
            'value': ATTACK,
        }

    def test_get_does_not_mutate_classsection_room_alias(self):
        resp = self.client.get(ENDPOINT, self._params(self.section.id))
        self.assertEqual(resp.status_code, 200)
        self.section.refresh_from_db()
        self.assertEqual(self.section.room_alias, ORIGINAL)

    def test_get_does_not_mutate_offering_room_alias(self):
        resp = self.client.get(ENDPOINT, self._params(self.offering.id))
        self.assertEqual(resp.status_code, 200)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.room_alias, ORIGINAL)

    def test_post_does_not_mutate_room_alias(self):
        resp = self.client.post(ENDPOINT, self._params(self.section.id))
        self.assertEqual(resp.status_code, 200)
        self.section.refresh_from_db()
        self.assertEqual(self.section.room_alias, ORIGINAL)
        self.offering.refresh_from_db()
        self.assertEqual(self.offering.room_alias, ORIGINAL)
