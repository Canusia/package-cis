"""cis's own SIS calls use the record's campus (package_ethos#4).

Rule: the record decides the campus. A registration's campus is its section's
course campus; a term's campus is its academic year's campus.
"""
import importlib.util
import uuid
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import Group
from django.test import TestCase, RequestFactory, override_settings

from cis.campus_context import campus_context, current_campus_or_none
from cis.models import CustomUser
from cis.models.course import Campus, Cohort, Course
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import Term, AcademicYear

if importlib.util.find_spec('ethos.ethos'):
    ETHOS_PATH = 'ethos.ethos.library.ethos.Ethos'
else:
    ETHOS_PATH = 'ethos.library.ethos.Ethos'


class _Recorder:
    """Stands in for the Ethos class; records the campus of each client."""

    def __init__(self):
        self.campuses = []
        self.instances = []

    def __call__(self, campus=None):
        self.campuses.append(campus)
        inst = MagicMock(name='EthosClient')
        inst.campus = campus
        inst.get_academic_period_id.return_value = str(uuid.uuid4())
        inst.get_child_academic_periods.return_value = []
        self.instances.append(inst)
        return inst


class SendToSisCampusTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.create_user(
            username='cron', email='cron@example.com', password='x')
        self.camp_a = Campus.objects.create(name='A College', code='AAA')
        self.camp_b = Campus.objects.create(name='B College', code='BBB')
        self.admin = CustomUser.objects.create_superuser(
            username='root', email='root@example.com', password='x')
        cohort = Cohort.objects.create(name='Astronomy', designator='A')
        self.regs = []
        for i, campus in enumerate([self.camp_a, self.camp_b, self.camp_a]):
            ay = AcademicYear.objects.create(name=f'AY{i}', campus=campus)
            term = Term.objects.create(
                label=f'Fall {i}', code=f'26F{i}', academic_year=ay)
            course = Course.objects.create(
                catalog_number=f'00{i}', title=f'Course {i}', name=f'A 00{i}',
                cohort=cohort, campus=campus)
            section = ClassSection.objects.create(
                course=course, term=term, campus=campus, class_number=f'C-{i}',
                section_number=f'{i}', external_sis_id=uuid.uuid4())
            user = CustomUser.objects.create_user(
                username=f'stu{i}', email=f'stu{i}@example.com', password='x')
            student = Student.objects.create(user=user, sis_id=uuid.uuid4())
            with campus_context(campus):
                reg = StudentRegistration.objects.create(
                    student=student, class_section=section,
                    status='applied', status_changed_on={})
            self.regs.append(reg)

    @override_settings(MULTI_CAMPUS=True)
    def test_bulk_send_mirrors_each_record_in_its_campus(self):
        from cis.views.registration import send_to_sis
        rec = _Recorder()
        seen = []
        svc = MagicMock()

        def _mirror(record, request):
            seen.append((record.pk, current_campus_or_none()))
            return (True, [])
        svc.mirror_to_sis.side_effect = _mirror

        request = RequestFactory().get('/ce/registration/send_to_sis')
        request.user = self.admin
        with patch(ETHOS_PATH, rec), \
             patch('cis.views.registration.get_tenant_service', return_value=svc), \
             patch('cis.views.registration.processable_ids',
                   return_value=[r.pk for r in self.regs]), \
             patch('cis.views.registration.render') as render:
            send_to_sis(request)

        # the view builds no Ethos client itself; the tenant service does
        self.assertEqual(rec.campuses, [])
        # records interleaved A, B, A are mirrored under their own campus
        # (pks may be UUIDs, so the view's order_by('pk') need not match A, B, A)
        campus_of = {self.regs[0].pk: self.camp_a, self.regs[1].pk: self.camp_b,
                     self.regs[2].pk: self.camp_a}
        self.assertEqual([c for _, c in seen],
                         [campus_of[pk] for pk in sorted(campus_of)])
        self.assertEqual(sorted(pk for pk, _ in seen), sorted(campus_of))


class TermLookupCampusTests(TestCase):
    def setUp(self):
        self.campus = Campus.objects.create(name='A College', code='AAA')
        ay = AcademicYear.objects.create(name='AYX', campus=self.campus)
        self.term = Term.objects.create(
            label='Fall X', code='26FX', academic_year=ay,
            external_sis_id=uuid.uuid4())

    def _post(self):
        request = RequestFactory().post('/ce/term/bulk_actions',
                                        {'ids[]': [str(self.term.pk)]})
        return request

    def test_sis_id_lookup_uses_terms_campus(self):
        from cis.actions.term import lookup_sis_id
        rec = _Recorder()
        with patch('cis.actions.term.Ethos', rec):
            lookup_sis_id(self._post())
        self.assertEqual(rec.campuses, [self.campus])

    def test_pull_sub_terms_uses_terms_campus(self):
        from cis.actions.term import pull_sub_terms
        rec = _Recorder()
        with patch('cis.actions.term.Ethos', rec):
            pull_sub_terms(self._post())
        self.assertEqual(rec.campuses, [self.campus])
