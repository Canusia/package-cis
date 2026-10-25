"""Recommender buckets: splitting a school's recommendation caseload by
student last-name initial (cis.services.recommender_scope).

The per-student check, the queryset scope and the digest split must agree —
`test_three_surfaces_agree` pins that — so a counselor never sees a student on
the list they cannot open, or is emailed about a student who is not theirs.
"""
from unittest.mock import patch

from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.test import TestCase

from cis.models.course import Cohort, Course
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.highschool_administrator import (
    ANY_CAMPUS, HSAdminPerm, HSAdministrator, HSAdministratorPosition, HSPosition)
from cis.models.recommender_bucket import RecommenderBucket
from cis.models.section import ClassSection, StudentRegistration
from cis.models.student import Student
from cis.models.term import AcademicYear, Term
from cis.services import recommender_scope as rs


class RecommenderBucketTestBase(TestCase):
    _seq = 0

    @classmethod
    def _n(cls):
        RecommenderBucketTestBase._seq += 1
        return RecommenderBucketTestBase._seq

    def setUp(self):
        Group.objects.get_or_create(name='student')
        CustomUser.objects.get_or_create(username='cron', defaults={'email': 'cron@localhost'})
        self.hs = HighSchool.objects.create(name='Lincoln High', status='Active')
        self.other_hs = HighSchool.objects.create(name='Roosevelt High', status='Active')
        self.role = HSPosition.objects.create(name=f'Counselor {self._n()}')
        ay = AcademicYear.objects.create(name=f'AY {self._n()}')
        self.term = Term.objects.create(label='Fall', code=f'F{self._n()}', academic_year=ay)
        self.cohort = Cohort.objects.create(name='English', designator='ENGL')

    def admin(self, name, highschool=None, perm=True, status='Active'):
        n = self._n()
        user = CustomUser.objects.create(
            username=f'adm{n}', email=f'{name.lower()}{n}@x.com', last_name=name)
        hsadmin = HSAdministrator.objects.create(user=user)
        position = HSAdministratorPosition.objects.create(
            hsadmin=hsadmin, highschool=highschool or self.hs, position=self.role,
            status=status)
        if perm:
            position.grant(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION)
        return hsadmin, position

    def bucket(self, start, end, *positions, highschool=None):
        hs = highschool or self.hs
        b = RecommenderBucket.objects.create(
            highschool=hs, name=f'{start}-{end} {self._n()}', start_letter=start, end_letter=end)
        rs.set_bucket_members(b, positions)
        return b

    def student(self, last_name, highschool=None):
        n = self._n()
        user = CustomUser.objects.create(
            username=f'stu{n}', email=f'stu{n}@x.com', last_name=last_name)
        return Student.objects.create(user=user, highschool=highschool or self.hs, grade_level='JR')

    def register(self, student, host='school'):
        """`host`: the section's high school; default this school, None for none."""
        n = self._n()
        course = Course.objects.create(
            name=f'ENGL {n}', title='Comp', catalog_number='101', cohort=self.cohort,
            status='Active', registration_eligibility=['JR*'])
        section = ClassSection.objects.create(
            course=course, term=self.term, highschool=self.hs if host == 'school' else host,
            registration_term=self.term,
            class_number=f'C{n:05d}', section_number='01')
        return StudentRegistration.objects.create(
            student=student, class_section=section, status='applied', status_changed_on={})

    def scoped(self, hsadmin, campus=None):
        """Students with a registration `hsadmin` may recommend for."""
        return {r.student for r in rs.scope_registrations(
            StudentRegistration.objects.all(), hsadmin, campus)}

    def set_mode(self, mode):
        from cis.models.settings import Setting
        from cis.settings.counselor_recommendation import counselor_recommendation
        Setting.objects.update_or_create(
            key=counselor_recommendation.key, defaults={'value': {
                'upload_label': 'x', 'require_grade_level_match': True,
                'recommending_school': mode}})


class InitialTests(RecommenderBucketTestBase):
    NAMES = ['Smith', ' smith', "O'Brien", 'de la Cruz', '', 'Ávila', 'ñúñez', 'Øster',
             'Łukasz', 'ıl', '1st', 'ßeta', 'zed', 'Иванов', 'Ærø']

    def test_python_and_sql_initials_agree_on_a_to_z(self):
        students = {name: self.student(name) for name in self.NAMES}
        rows = dict(Student.objects.filter(pk__in=[s.pk for s in students.values()])
                    .annotate(i=rs.student_initial_sql()).values_list('pk', 'i'))
        for name, s in students.items():
            sql = rows[s.pk] if rows[s.pk] in rs.LETTERS else None
            self.assertEqual(rs.student_initial(s), sql, name)

    def test_expected_initials(self):
        self.assertEqual(rs.initial_of(' smith'), 'S')
        self.assertEqual(rs.initial_of("O'Brien"), 'O')
        self.assertIsNone(rs.initial_of(''))
        self.assertIsNone(rs.initial_of(None))
        self.assertEqual(rs.initial_of('Ávila'), 'A')
        self.assertEqual(rs.initial_of('ñúñez'), 'N')
        self.assertEqual(rs.initial_of('Øster'), 'O')
        self.assertIsNone(rs.initial_of('1st'))
        self.assertIsNone(rs.initial_of('Иванов'))


class ScopeTests(RecommenderBucketTestBase):
    def setUp(self):
        super().setUp()
        self.adams = self.student('Adams')
        self.green = self.student('Green')
        self.young = self.student('Young')
        self.avila = self.student('Ávila')
        self.ivanov = self.student('Иванов')
        self.elsewhere = self.student('Abbot', highschool=self.other_hs)
        for s in (self.adams, self.green, self.young, self.avila, self.ivanov, self.elsewhere):
            self.register(s)

    def test_unranged_admin_covers_whole_school(self):
        admin, _ = self.admin('Lead')
        self.assertEqual(self.scoped(admin),
                         {self.adams, self.green, self.young, self.avila, self.ivanov})

    def test_ranged_admin_covers_only_their_letters(self):
        admin, pos = self.admin('Lee')
        self.bucket('A', 'F', pos)
        self.assertEqual(self.scoped(admin), {self.adams, self.avila})
        self.assertTrue(admin.can_manage_student_recommendation(self.hs.id, student=self.avila))
        self.assertTrue(admin.can_manage_student_recommendation(self.hs.id, student=self.adams))
        self.assertFalse(admin.can_manage_student_recommendation(self.hs.id, student=self.green))

    def test_split_caseload_across_two_buckets(self):
        admin, pos = self.admin('Lee')
        self.bucket('A', 'C', pos)
        self.bucket('X', 'Z', pos)
        self.assertEqual(self.scoped(admin), {self.adams, self.avila, self.young})

    def test_accents_fold_and_other_scripts_match_no_bucket(self):
        admin, pos = self.admin('Lee')
        self.bucket('A', 'Z', pos)
        self.assertIn(self.avila, self.scoped(admin))
        self.assertNotIn(self.ivanov, self.scoped(admin))

    def test_overlap_both_admins_see_shared_letters(self):
        a, pa = self.admin('Lee')
        b, pb = self.admin('Ruiz')
        self.bucket('A', 'H', pa)
        self.bucket('E', 'Z', pb)
        self.assertIn(self.green, self.scoped(a))
        self.assertIn(self.green, self.scoped(b))

    def test_without_permission_or_inactive_nothing(self):
        no_perm, pos = self.admin('NoPerm', perm=False)
        self.assertEqual(self.scoped(no_perm), set())
        inactive, _ = self.admin('Gone', status='Inactive')
        self.assertEqual(self.scoped(inactive), set())
        self.assertEqual(self.scoped(None), set())

    def test_school_level_check_unchanged_without_student(self):
        admin, pos = self.admin('Lee')
        self.bucket('A', 'F', pos)
        self.assertTrue(admin.can_manage_student_recommendation(self.hs.id))

    def test_distinct_on_after_scope(self):
        admin, pos = self.admin('Lee')
        self.bucket('A', 'F', pos)
        reg_a = self.register(self.adams)
        qs = rs.scope_registrations(
            StudentRegistration.objects.filter(student__in=[self.adams, self.green]), admin)
        self.assertEqual(len(qs), 2)
        self.assertIn(reg_a, qs)
        # DISTINCT ON after the scope still works (Pending feed shape).
        self.assertEqual(len(list(qs.order_by('student__id').distinct('student__id'))), 1)

    def test_campus_grant_still_respected(self):
        from django.contrib.sites.models import Site
        from cis.models.course import Campus
        admin, pos = self.admin('Lee', perm=False)
        campus = Campus.objects.create(name='North', code='N1', site=Site.objects.create(
            domain='n.example.edu', name='N'))
        other = Campus.objects.create(name='South', code='S1', site=Site.objects.create(
            domain='s.example.edu', name='S'))
        pos.grant(HSAdminPerm.MANAGE_STUDENT_RECOMMENDATION, campus=campus)
        self.bucket('A', 'F', pos)
        self.assertEqual(self.scoped(admin, campus), {self.adams, self.avila})
        self.assertEqual(self.scoped(admin, other), set())
        self.assertEqual(self.scoped(admin, ANY_CAMPUS), {self.adams, self.avila})


class ThreeSurfacesTests(RecommenderBucketTestBase):
    def test_three_surfaces_agree(self):
        lead, _ = self.admin('Lead')                    # unranged: everyone
        lee, p_lee = self.admin('Lee')
        ruiz, p_ruiz = self.admin('Ruiz')
        self.bucket('A', 'F', p_lee)
        self.bucket('F', 'M', p_ruiz)                   # overlap on F; gap N–Z
        students = [self.student(n) for n in ('Adams', 'Fox', 'Kim', 'Young', 'Ávila', '', '1st')]
        regs = [self.register(s) for s in students]
        admins = [lead, lee, ruiz]

        expected = {}
        for s in students:
            expected[s] = {a for a in admins
                           if a.can_manage_student_recommendation(self.hs.id, student=s)}
        for s, r in zip(students, regs):
            self.assertEqual(set(rs.recommenders_for_registration(r)), expected[s], s.user.last_name)
        for a in admins:
            self.assertEqual(self.scoped(a), {s for s in students if a in expected[s]})

        emailed = {}
        groups = rs.split_by_recommenders(
            self.hs, StudentRegistration.objects.filter(pk__in=[r.pk for r in regs]))
        for g in groups:
            for r in g['registrations']:
                emailed[r.student] = set(g['recipients'])
        for s in students:
            self.assertEqual(emailed.get(s, set()), {a.user.email for a in expected[s]})
        # Fox (overlap) gets both rangers + lead; Young (gap) only the fallback.
        fox, young = students[1], students[3]
        self.assertEqual(expected[fox], {lead, lee, ruiz})
        self.assertEqual(expected[young], {lead})

    def test_uncovered_student_is_left_out_of_digest(self):
        _, pos = self.admin('Lee')
        self.bucket('A', 'F', pos)
        reg = self.register(self.student('Young'))
        groups = rs.split_by_recommenders(self.hs, StudentRegistration.objects.filter(pk=reg.pk))
        self.assertEqual(groups, [])


class RecommendingSchoolTests(RecommenderBucketTestBase):
    """The Counselor Rec. Form setting's recommending school: the student's
    high school (default), the class's host high school, or both."""

    def setUp(self):
        super().setUp()
        self.home, _ = self.admin('Home')                         # student's school
        self.host, self.p_host = self.admin('Host', highschool=self.other_hs)
        self.stu = self.student('Young')                          # attends self.hs
        self.reg = self.register(self.stu, host=self.other_hs)    # class at other_hs

    def pending(self, school):
        return set(StudentRegistration.get_pending_recommendations(highschool_ids=[school.id]))

    def test_default_is_the_students_school(self):
        self.assertEqual(rs.recommending_school_mode(), 'student')
        self.assertEqual(self.scoped(self.home), {self.stu})
        self.assertEqual(self.scoped(self.host), set())
        self.assertEqual(self.pending(self.hs), {self.reg})
        self.assertEqual(self.pending(self.other_hs), set())

    def test_unknown_value_means_students_school(self):
        self.set_mode('nonsense')
        self.assertEqual(rs.recommending_school_mode(), 'student')

    def test_class_school(self):
        self.set_mode('class')
        self.assertEqual(self.scoped(self.home), set())
        self.assertEqual(self.scoped(self.host), {self.stu})
        self.assertEqual(self.pending(self.hs), set())
        self.assertEqual(self.pending(self.other_hs), {self.reg})
        self.assertEqual(set(rs.recommenders_for_registration(self.reg)), {self.host})

    def test_class_school_falls_back_when_section_has_none(self):
        self.set_mode('class')
        reg = self.register(self.student('Adams'), host=None)
        self.assertIn(reg, self.pending(self.hs))
        self.assertEqual(set(rs.recommenders_for_registration(reg)), {self.home})

    def test_both(self):
        self.set_mode('both')
        self.assertEqual(self.scoped(self.home), {self.stu})
        self.assertEqual(self.scoped(self.host), {self.stu})
        self.assertEqual(set(rs.recommenders_for_registration(self.reg)), {self.home, self.host})
        groups = rs.recommender_groups(StudentRegistration.objects.filter(pk=self.reg.pk))
        self.assertEqual({(g['highschool'], tuple(g['recipients'])) for g in groups}, {
            (self.hs, (self.home.user.email,)),
            (self.other_hs, (self.host.user.email,))})

    def test_buckets_apply_at_the_host_school(self):
        self.set_mode('class')
        self.bucket('A', 'F', self.p_host, highschool=self.other_hs)
        self.assertEqual(self.scoped(self.host), set())              # Young is not A–F
        adams = self.student('Adams')
        self.register(adams, host=self.other_hs)
        self.assertEqual(self.scoped(self.host), {adams})
        self.assertEqual(rs.recommender_groups(
            StudentRegistration.objects.filter(pk=self.reg.pk)), [])

    def test_digest_default_groups_by_recommending_school(self):
        self.set_mode('class')
        with patch('cis.utils.registration_terms', return_value=[self.term]):
            groups = StudentRegistration.counselor_notification_groups()
        self.assertEqual([(g['highschool'], g['recipients']) for g in groups],
                         [(self.other_hs, [self.host.user.email])])

    def test_cis_defaults_without_tenant_overrides(self):
        self.set_mode('class')
        with patch('cis.models.section._tenant_registration_override', return_value=None), \
                patch('cis.utils.registration_terms', return_value=[self.term]):
            self.assertEqual(self.pending(self.other_hs), {self.reg})
            self.assertEqual(self.pending(self.hs), set())
            groups = StudentRegistration.counselor_notification_groups()
        self.assertEqual([(g['highschool'], g['recipients']) for g in groups],
                         [(self.other_hs, [self.host.user.email])])

    def test_coverage_counts_follow_the_mode(self):
        self.register(self.student('1st'), host=self.other_hs)
        with patch('cis.utils.registration_terms', return_value=[self.term]):
            self.assertEqual(rs.coverage(self.other_hs)['non_az_students'], 0)
            self.set_mode('class')
            self.assertEqual(rs.coverage(self.other_hs)['non_az_students'], 1)

    def test_setting_form_saves_the_choice(self):
        from cis.settings.counselor_recommendation import SettingForm
        form = SettingForm(data={'upload_label': 'x', 'recommending_school': 'both'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form._to_python()['recommending_school'], 'both')
        self.assertFalse(SettingForm(data={'upload_label': 'x',
                                           'recommending_school': 'nope'}).is_valid())


class StudentRecommendationPerSchoolTests(RecommenderBucketTestBase):
    """StudentRecommendation.highschool: one record per student, term and
    recommending school; a row with no school is the student's own."""

    def setUp(self):
        super().setUp()
        self.home, _ = self.admin('Home')
        self.host, _ = self.admin('Host', highschool=self.other_hs)
        self.stu = self.student('Young')
        self.reg_home = self.register(self.stu)
        self.reg_host = self.register(self.stu, host=self.other_hs)

    def rec(self, highschool=None):
        from cis.models.student import StudentRecommendation
        return StudentRecommendation.objects.create(
            student=self.stu, term=self.term, highschool=highschool, recommendation={})

    def test_one_record_per_school(self):
        self.rec()
        self.rec(self.other_hs)
        for school in (None, self.other_hs):
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.rec(school)

    def test_students_school_mode_any_record_counts(self):
        self.rec(self.other_hs)
        self.assertTrue(self.stu.has_recommendation(self.term.id))
        self.assertTrue(self.reg_home.has_recommendation())
        self.assertTrue(self.reg_host.has_recommendation())

    def test_class_mode_each_recommending_school_must_file(self):
        self.set_mode('class')
        self.rec()                                            # student's own school
        self.assertFalse(self.stu.has_recommendation(self.term.id))
        self.assertFalse(self.reg_host.has_recommendation())
        self.assertIsNone(self.reg_host.get_recommendation())
        hosted = self.rec(self.other_hs)
        self.assertTrue(self.stu.has_recommendation(self.term.id))
        self.assertTrue(self.reg_host.has_recommendation())
        self.assertEqual(self.reg_host.get_recommendation(), hosted)
        self.assertTrue(self.stu.has_recommendation(self.term.id, highschool_id=self.other_hs.id))

    def test_cis_default_has_recommendation(self):
        self.set_mode('class')
        self.rec()
        with patch('cis.models.section._tenant_registration_override', return_value=None):
            self.assertTrue(self.reg_home.has_recommendation())
            self.assertFalse(self.reg_host.has_recommendation())

    def test_annotation_agrees_with_the_property(self):
        from cis.views.eager import annotate_registration_flags
        self.rec()
        regs = StudentRegistration.objects.filter(pk__in=[self.reg_home.pk, self.reg_host.pk])
        for mode in ('student', 'class', 'both'):
            self.set_mode(mode)
            with patch('cis.models.section._tenant_registration_override', return_value=None):
                annotated = {r.pk: r._has_recommendation for r in annotate_registration_flags(regs)}
                plain = {r.pk: r.has_recommendation() for r in regs}
            self.assertEqual(annotated, plain, mode)

    def test_get_recommendation_without_school_prefers_the_students_own(self):
        hosted = self.rec(self.other_hs)
        self.assertEqual(self.stu.get_recommendation(self.term.id), hosted)
        own = self.rec()
        self.assertEqual(self.stu.get_recommendation(self.term.id), own)
        self.assertEqual(self.stu.get_recommendation(self.term.id, self.other_hs.id), hosted)

    def test_filing_school(self):
        regs = StudentRegistration.objects.filter(pk__in=[self.reg_home.pk, self.reg_host.pk])
        self.assertIsNone(rs.filing_school(self.host, regs, self.stu))       # student mode
        self.set_mode('class')
        self.assertEqual(rs.filing_school(self.host, regs, self.stu), self.other_hs)
        self.assertIsNone(rs.filing_school(self.home, regs, self.stu))


class SchoolRuleCacheTests(RecommenderBucketTestBase):
    def test_one_read_per_request_and_saves_invalidate(self):
        from django.core.signals import request_finished, request_started
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        # The receivers themselves: sending request_started would also close
        # the test's database connection.
        self.assertIn('cis_recommending_school_rule_start', str(request_started.receivers))
        self.assertIn('cis_recommending_school_rule_end', str(request_finished.receivers))
        rs._start_request_cache()
        try:
            with CaptureQueriesContext(connection) as captured:
                for _ in range(3):
                    self.assertEqual(rs.school_rule(), 'student')
            self.assertEqual(len(captured), 1)
            self.set_mode('class')
            self.assertEqual(rs.school_rule(), 'class')
        finally:
            rs._end_request_cache()
        with CaptureQueriesContext(connection) as captured:
            rs.school_rule()
            rs.school_rule()
        self.assertEqual(len(captured), 2)                        # outside a request


class MultiCampusRuleTests(RecommenderBucketTestBase):
    """Each campus's own setting decides for its registrations."""

    def test_rule_per_campus(self):
        from django.contrib.sites.models import Site
        from cis.models.course import Campus
        from cis.models.settings import Setting
        from cis.settings.counselor_recommendation import counselor_recommendation
        north = Campus.objects.create(name='North', code='N1', site=Site.objects.create(
            domain='n.example.edu', name='N'))
        south = Campus.objects.create(name='South', code='S1', site=Site.objects.create(
            domain='s.example.edu', name='S'))
        for campus, mode in ((north, 'class'), (south, 'student')):
            Setting.objects.create(key=counselor_recommendation.key, campus=campus,
                                   value={'recommending_school': mode})
        stu = self.student('Young')
        regs = {}
        for campus in (north, south):
            reg = self.register(stu, host=self.other_hs)
            reg.class_section.course.campus = campus
            reg.class_section.course.save()
            regs[campus] = reg
        with patch('cis.campus_context.is_multi_campus', return_value=True):
            rule = rs.school_rule()
            self.assertEqual(rule, {'class': [north.id], 'student': [south.id]})
            at_host = set(StudentRegistration.objects.filter(
                rs.recommending_school_q([self.other_hs.id], mode=rule)))
            at_home = set(StudentRegistration.objects.filter(
                rs.recommending_school_q([self.hs.id], mode=rule)))
        self.assertEqual(at_host, {regs[north]})
        self.assertEqual(at_home, {regs[south]})


class CoverageAndValidationTests(RecommenderBucketTestBase):
    def test_coverage_gaps_overlaps_fallback(self):
        _, p1 = self.admin('Lee')
        _, p2 = self.admin('Ruiz')
        self.bucket('A', 'F', p1)
        self.bucket('E', 'M', p2)
        self.bucket('X', 'Z')                           # no members: covers nothing
        self.register(self.student('1st'))              # pending, matches no bucket
        self.student('2nd')                             # not pending: not counted
        with patch('cis.utils.registration_terms', return_value=[self.term]):
            cov = rs.coverage(self.hs)
        self.assertEqual(cov['gaps'], ['N–Z'])
        self.assertEqual(cov['overlaps'], ['E–F'])
        self.assertEqual(cov['fallback'], [])
        self.assertTrue(cov['has_buckets'])
        self.assertEqual(cov['non_az_students'], 1)

        lead, _ = self.admin('Lead')
        self.assertEqual(rs.coverage(self.hs)['fallback'], [str(lead)])

    def test_no_buckets(self):
        self.admin('Lead')
        cov = rs.coverage(self.hs)
        self.assertFalse(cov['has_buckets'])
        self.assertEqual(cov['gaps'], ['A–Z'])

    def test_bucket_from_another_school_rejected(self):
        _, pos = self.admin('Lee')
        b = RecommenderBucket.objects.create(
            highschool=self.other_hs, name='A-F', start_letter='A', end_letter='F')
        with self.assertRaises(ValueError):
            rs.assign_buckets(pos, [b])
        with self.assertRaises(ValueError):
            rs.set_bucket_members(b, [pos])

    def test_db_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            RecommenderBucket.objects.create(
                highschool=self.hs, name='bad', start_letter='G', end_letter='A')
        RecommenderBucket.objects.create(
            highschool=self.hs, name='dup', start_letter='A', end_letter='B')
        with self.assertRaises(IntegrityError), transaction.atomic():
            RecommenderBucket.objects.create(
                highschool=self.hs, name='dup', start_letter='C', end_letter='D')


class CEScreenTests(RecommenderBucketTestBase):
    def setUp(self):
        super().setUp()
        Group.objects.get_or_create(name='ce')
        self.staff = CustomUser.objects.create_user(
            username=f'ce{self._n()}', email=f'ce{self._n()}@x.com', password='x')
        self.staff.groups.add(Group.objects.get(name='ce'))
        self.nobody = CustomUser.objects.create_user(
            username=f'no{self._n()}', email=f'no{self._n()}@x.com', password='x')
        self.lee, self.p_lee = self.admin('Lee')

    def call(self, view, user, post=None, **kwargs):
        import json
        from django.test import RequestFactory
        req = RequestFactory().post('/x', post or {})
        req.user = user
        resp = view(req, **kwargs)
        return resp, json.loads(resp.content) if resp['Content-Type'].startswith(
            'application/json') else None

    def test_add_modal_then_save(self):
        from cis.views import recommender_bucket as v
        resp, data = self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id)
        self.assertEqual(data['outcome'], 'modal')
        self.assertIn(str(self.p_lee.id), data['html'])

        resp, data = self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id, post={
            'apply': '1', 'name': 'A–F', 'start_letter': 'A', 'end_letter': 'F',
            'members': [str(self.p_lee.id)]})
        self.assertEqual(resp.status_code, 200, data)
        bucket = self.hs.recommender_buckets.get()
        self.assertEqual(list(bucket.positions.all()), [self.p_lee])
        from cis.models.note import HighSchoolNote
        self.assertTrue(HighSchoolNote.objects.filter(
            highschool=self.hs, note__contains='A–F').exists())

    def test_reversed_range_and_duplicate_name_rejected(self):
        from cis.views import recommender_bucket as v
        resp, _ = self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id, post={
            'apply': '1', 'name': 'x', 'start_letter': 'G', 'end_letter': 'A'})
        self.assertEqual(resp.status_code, 400)
        self.bucket('A', 'B')
        name = self.hs.recommender_buckets.get().name
        resp, _ = self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id, post={
            'apply': '1', 'name': name.upper(), 'start_letter': 'C', 'end_letter': 'D'})
        self.assertEqual(resp.status_code, 400)

    def test_member_from_another_school_rejected(self):
        from cis.views import recommender_bucket as v
        _, elsewhere = self.admin('Far', highschool=self.other_hs)
        resp, _ = self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id, post={
            'apply': '1', 'name': 'A–F', 'start_letter': 'A', 'end_letter': 'F',
            'members': [str(elsewhere.id)]})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(self.hs.recommender_buckets.exists())

    def test_edit_keeps_members_the_form_cannot_show(self):
        from cis.views import recommender_bucket as v
        bucket = self.bucket('A', 'F', self.p_lee)
        self.p_lee.status = 'Inactive'
        self.p_lee.save()
        resp, _ = self.call(v.ce_bucket_edit, self.staff, bucket_id=bucket.id, post={
            'apply': '1', 'name': 'renamed', 'start_letter': 'A', 'end_letter': 'F'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(bucket.positions.all()), [self.p_lee])

    def test_staff_need_every_campus_link(self):
        from unittest.mock import patch as _patch
        from cis.views import recommender_bucket as v
        with _patch('cis.views.recommender_bucket.ce_can_manage', return_value=False):
            resp, _ = self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id)
        self.assertEqual(resp.status_code, 403)

    def test_edit_and_delete(self):
        from cis.views import recommender_bucket as v
        bucket = self.bucket('A', 'F', self.p_lee)
        resp, _ = self.call(v.ce_bucket_edit, self.staff, bucket_id=bucket.id, post={
            'apply': '1', 'name': bucket.name, 'start_letter': 'A', 'end_letter': 'G',
            'members': [str(self.p_lee.id)]})
        self.assertEqual(resp.status_code, 200)
        bucket.refresh_from_db()
        self.assertEqual(bucket.end_letter, 'G')

        resp, data = self.call(v.ce_bucket_delete, self.staff, bucket_id=bucket.id)
        self.assertIn(str(self.lee), data['html'])     # names who becomes unranged
        resp, _ = self.call(v.ce_bucket_delete, self.staff, bucket_id=bucket.id,
                            post={'apply': '1'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(RecommenderBucket.objects.filter(pk=bucket.pk).exists())

    def test_note_escapes_bucket_name(self):
        from cis.models.note import HighSchoolNote
        from cis.views import recommender_bucket as v
        self.call(v.ce_bucket_add, self.staff, record_id=self.hs.id, post={
            'apply': '1', 'name': '<b>x</b>', 'start_letter': 'A', 'end_letter': 'F'})
        note = HighSchoolNote.objects.get(highschool=self.hs).note
        self.assertIn('&lt;b&gt;x&lt;/b&gt;', note)

    def test_non_ce_forbidden(self):
        from cis.views import recommender_bucket as v
        resp, _ = self.call(v.ce_bucket_add, self.nobody, record_id=self.hs.id)
        self.assertEqual(resp.status_code, 403)

    def test_tab_renders_buckets_and_coverage(self):
        from cis.views import highschool as hs_views
        from django.test import RequestFactory
        self.bucket('A', 'F', self.p_lee)
        req = RequestFactory().get('/x')
        req.user = self.staff
        body = hs_views.tab(req, record_id=self.hs.id, tab_slug='recommenders').content.decode()
        self.assertIn('Gap: G–Z', body)
        self.assertIn('no fallback', body)
        self.assertIn(str(self.lee), body)
