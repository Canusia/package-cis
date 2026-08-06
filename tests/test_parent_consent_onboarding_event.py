"""Parent consent completes its onboarding step.

A tenant enabling the `parent_consent` onboarding step wires an event to that
step key, but `cis` never sent one: `ParentConsentForm.save()` and the CE
`waive_parent_consent()` view both wrote the `ParentConsent` row and returned.
The chevron stayed on "Obtain parent/guardian consent" forever. The sibling
`StudentAgreementForm.save()` has dispatched `STUDENT_AGREEMENT_SIGNED` all
along, which is the shape these follow. See ewu#54.
"""
import datetime
import uuid

from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase

from student_onboarding import events as onboarding_events
from student_onboarding.signals import onboarding_event

from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection, StudentRegistration
from cis.models.settings import Setting
from cis.models.student import ParentConsent, Student
from cis.models.term import AcademicYear, Term


def _u(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


class _CapturedEvents:
    """Collect onboarding_event sends for the duration of a block."""

    def __init__(self):
        self.events = []

    def __enter__(self):
        onboarding_event.connect(self._receive)
        return self

    def __exit__(self, *exc):
        onboarding_event.disconnect(self._receive)
        return False

    def _receive(self, sender, event=None, student=None, **kwargs):
        self.events.append((event, student))

    def names(self):
        return [name for name, _student in self.events]


class ParentConsentEventTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})

        hs = HighSchool.objects.create(name=_u('HS'))
        u = CustomUser.objects.create_user(
            username=_u('stu'), email=f'{_u("stu")}@example.com', password='x')
        self.student = Student.objects.create(
            user=u, highschool=hs, grade_level='FR')

        ay = AcademicYear.objects.create(name=_u('AY'))
        self.term = Term.objects.create(
            academic_year=ay, code='F32', label=_u('Fall'))
        campus = Campus.objects.create(name=_u('Campus'))
        cohort = Cohort.objects.create(name=_u('Cohort'), designator='PC')
        course = Course.objects.create(
            catalog_number='101', title='Intro', name=_u('COURSE'),
            cohort=cohort, credit_hours=3, campus=campus)
        section = ClassSection.objects.create(
            term=self.term, course=course, class_number=_u('CN'),
            section_number='01', highschool=hs)
        # ParentConsentForm.save() only writes for terms the student is
        # actually registered in.
        StudentRegistration.objects.create(
            student=self.student, class_section=section,
            status='applied', status_changed_on={})

        prefix = __import__("django").conf.settings.CAMPUS_CODE_PREFIX
        Setting.objects.update_or_create(
            key=f'{prefix}_cis_registrations',
            defaults={'value': {'registration_terms': [str(self.term.id)]}})
        # Saving a ParentConsent sends the "consent received" notification,
        # which reads these keys; without them the write raises KeyError and
        # both call sites swallow it in a bare `except:`.
        Setting.objects.update_or_create(
            key=f'{prefix}_regis_email',
            defaults={'value': {
                'is_active': 'No',
                'parent_consent_recv_subject': 'Consent received',
                'parent_consent_recv': 'Consent received.',
            }})

    def test_constant_is_exported_by_the_package(self):
        """Tenants use a bare 'parent_consent_signed' string today; the value
        must match or every existing catalog entry stops resolving."""
        self.assertEqual(
            onboarding_events.PARENT_CONSENT_SIGNED, 'parent_consent_signed')

    def test_form_save_fires_the_event(self):
        from cis.forms.student import ParentConsentForm

        form = ParentConsentForm(data={
            'action': 'submit_parent_consent',
            'student': str(self.student.id),
            'parent_signature': 'A Parent',
        })
        self.assertTrue(form.is_valid(), form.errors)

        with _CapturedEvents() as captured:
            form.save()

        self.assertIn(
            onboarding_events.PARENT_CONSENT_SIGNED, captured.names())

    def test_form_save_reports_the_right_student(self):
        from cis.forms.student import ParentConsentForm

        form = ParentConsentForm(data={
            'action': 'submit_parent_consent',
            'student': str(self.student.id),
            'parent_signature': 'A Parent',
        })
        self.assertTrue(form.is_valid(), form.errors)

        with _CapturedEvents() as captured:
            form.save()

        sent = dict(
            (name, student) for name, student in captured.events)
        self.assertEqual(
            sent[onboarding_events.PARENT_CONSENT_SIGNED].id, self.student.id)

    def test_ce_waive_fires_the_event(self):
        """The CE "mark as received" path writes the same row and must
        complete the same step."""
        from cis.views.student import waive_parent_consent

        staff = CustomUser.objects.create_superuser(
            username=_u('ce'), email=f'{_u("ce")}@example.com', password='x')
        request = RequestFactory().get(
            '/', {'id': str(self.student.id), 'term': str(self.term.id)})
        request.user = staff

        with _CapturedEvents() as captured:
            response = waive_parent_consent(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            onboarding_events.PARENT_CONSENT_SIGNED, captured.names())

    def test_waive_does_not_fire_when_the_write_fails(self):
        """Guard: the event states that consent exists, so it must not be sent
        for a write that did not happen."""
        from cis.views.student import waive_parent_consent

        ParentConsent.objects.create(
            student=self.student, term=self.term,
            parent_signature='Already there',
            parent_signed_on=datetime.datetime.now())

        staff = CustomUser.objects.create_superuser(
            username=_u('ce2'), email=f'{_u("ce2")}@example.com', password='x')
        request = RequestFactory().get(
            '/', {'id': str(self.student.id), 'term': str(self.term.id)})
        request.user = staff

        with _CapturedEvents() as captured:
            waive_parent_consent(request)

        self.assertNotIn(
            onboarding_events.PARENT_CONSENT_SIGNED, captured.names())
