"""ClassSection.meta never leaves the server through the API (#14).

On Ethos-imported tenants `meta` is the raw SIS section payload, including
`instructorRosterDetails[].instructor.credentials` (Banner IDs, usernames, UDC
IDs), and runs to several KB per section. /ce/api/class_section/ has no role
gate -- student, instructor and HS-admin pages call it -- and the serializer is
also nested in registration, drop-request, note and syllabus feeds. No client
reads `meta`; server code reads it off the model (sis_id, pretty_meta, the SIS
eligibility check), which this change does not touch.
"""
import uuid

from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in
from django.test import TestCase

from cis.models import CustomUser
from cis.models.course import Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.serializers import tables
from cis.serializers.class_section import ClassSectionSerializer
from cis.serializers.registration import StudentRegistrationSerializer

try:
    from django_login_history.models import post_login as _login_history_post_login
except Exception:  # pragma: no cover
    _login_history_post_login = None

SECRET = 'BANNER-ID-00990030'
SIS_META = {
    'id': str(uuid.uuid4()),
    'reportingAcademicPeriod': {'id': str(uuid.uuid4())},
    'instructorRosterDetails': [{
        'instructor': {'credentials': [{'type': 'bannerId', 'value': SECRET}]},
    }],
}


class ClassSectionMetaNotSerializedTests(TestCase):
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
        student_group, _ = Group.objects.get_or_create(name='student')
        if not CustomUser.objects.filter(username='cron').exists():
            CustomUser.objects.create_user(
                username='cron', email='cron@example.com', password='x')
        short = uuid.uuid4().hex[:8]
        cohort = Cohort.objects.create(name=f'Cohort-{short}', designator='A')
        course = Course.objects.create(
            catalog_number='101', title='History', name=f'H {short}', cohort=cohort)
        ay = AcademicYear.objects.create(name=f'AY-{short}')
        cls.term = Term.objects.create(label=f'Term-{short}', code=short, academic_year=ay)
        cls.section = ClassSection.objects.create(
            course=course, term=cls.term, class_number=f'H-{short}',
            section_number='H20', external_sis_id=uuid.uuid4(), meta=SIS_META)

        cls.student_user = CustomUser.objects.create_user(
            username=f'stu-{short}', email=f'{short}@example.com', password='x')
        cls.student_user.groups.add(student_group)
        cls.student = Student.objects.create(user=cls.student_user, sis_id=uuid.uuid4())
        cls.registration = StudentRegistration.objects.create(
            student=cls.student, class_section=cls.section,
            status='enrolled', status_changed_on={})

    def test_class_section_serializer_omits_meta(self):
        data = ClassSectionSerializer(self.section).data
        self.assertNotIn('meta', data)
        self.assertIn('class_number', data)

    def test_slim_and_trimmed_serializers_omit_meta(self):
        for cls in (tables.SlimClassSectionSerializer, tables.TrimmedClassSectionSerializer):
            self.assertNotIn('meta', cls(self.section).data, msg=cls.__name__)

    def test_nested_in_registration_omits_meta(self):
        data = StudentRegistrationSerializer(self.registration).data
        self.assertNotIn('meta', data['class_section'])

    def test_student_calling_class_section_api_gets_no_sis_payload(self):
        self.client.force_login(self.student_user)
        resp = self.client.get(
            f'/ce/api/class_section/?format=json&term={self.term.id}',
            REMOTE_ADDR='127.0.0.1')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(SECRET, resp.content.decode())
        self.assertNotIn('instructorRosterDetails', resp.content.decode())

    def test_model_still_holds_meta_for_server_side_readers(self):
        self.section.refresh_from_db()
        self.assertEqual(
            self.section.meta['reportingAcademicPeriod'], SIS_META['reportingAcademicPeriod'])
