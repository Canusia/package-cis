"""Potential Duplicate Students Export must export students, and only students.

The report self-joined cis_customuser -- the account table shared by every role
-- with no join to cis_student and no group filter, so instructors whose names
collided were exported alongside students. It also emitted one row of u1 per
matching u2, so an N-way name group produced N*(N-1) rows.
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.student import Student
from cis.reports.duplicate_students import duplicate_students

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class DuplicateStudentsReportTests(TestCase):
    def setUp(self):
        Group.objects.get_or_create(name='student')
        Group.objects.get_or_create(name='instructor')
        User.objects.get_or_create(
            username='cron', defaults={'email': 'cron@x.com'})
        self.report = duplicate_students()

    def _user(self, first, last, **extra):
        user = User.objects.create_user(
            username=f'u_{_sfx()}', email=f'u_{_sfx()}@x.com', password='x',
            first_name=first, last_name=last)
        for key, value in extra.items():
            setattr(user, key, value)
        if extra:
            user.save()
        return user

    def _student(self, first, last, **extra):
        return Student.objects.create(
            user=self._user(first, last, **extra), account_verified=True,
            meta={})

    def _instructor(self, first, last):
        user = self._user(first, last)
        user.groups.add(Group.objects.get(name='instructor'))
        return user

    def _ids(self):
        return [s.user_id for s in self.report.get_result({})]

    # --- the reported defect -------------------------------------------------

    def test_instructor_sharing_a_name_with_a_student_is_excluded(self):
        student = self._student('Jordan', 'Rivera')
        instructor = self._instructor('Jordan', 'Rivera')
        ids = self._ids()
        self.assertNotIn(instructor.id, ids)
        # And with no second *student* of that name, nothing is a duplicate.
        self.assertNotIn(student.user_id, ids)

    def test_two_instructors_sharing_a_name_produce_nothing(self):
        self._instructor('Sam', 'Okafor')
        self._instructor('Sam', 'Okafor')
        self.assertEqual(self._ids(), [])

    # --- correct student matching -------------------------------------------

    def test_two_students_sharing_a_name_both_appear(self):
        a = self._student('Alex', 'Chen')
        b = self._student('Alex', 'Chen')
        ids = self._ids()
        self.assertIn(a.user_id, ids)
        self.assertIn(b.user_id, ids)

    def test_a_unique_name_is_absent(self):
        solo = self._student('Wilhelmina', f'Unique{_sfx()}')
        self.assertNotIn(solo.user_id, self._ids())

    def test_three_way_group_yields_three_rows_not_six(self):
        for _ in range(3):
            self._student('Dana', 'Whitfield')
        ids = [i for i in self._ids()]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)

    def test_matching_ignores_case_and_surrounding_whitespace(self):
        a = self._student('maria', 'Santos')
        b = self._student('  Maria ', ' santos  ')
        ids = self._ids()
        self.assertIn(a.user_id, ids)
        self.assertIn(b.user_id, ids)

    def test_blank_names_are_not_grouped_together(self):
        a = self._student('', '')
        b = self._student('', '')
        ids = self._ids()
        self.assertNotIn(a.user_id, ids)
        self.assertNotIn(b.user_id, ids)

    def test_students_with_the_same_name_but_different_dob_still_group(self):
        # Matching is name-only on purpose: an abandoned account has no DOB,
        # and pairing it with the student's real account is the whole point.
        import datetime
        a = self._student('Noor', 'Haddad', date_of_birth=datetime.date(2008, 5, 1))
        b = self._student('Noor', 'Haddad', date_of_birth=None)
        ids = self._ids()
        self.assertIn(a.user_id, ids)
        self.assertIn(b.user_id, ids)

    # --- the diagnostic columns ---------------------------------------------

    def test_orphan_account_is_flagged_as_having_no_password(self):
        from cis.reports.duplicate_students import _COLUMNS
        orphan = self._student('Casey', 'Lindqvist')
        orphan.user.password = ''          # never reached complete_signup
        orphan.user.save()
        self._student('Casey', 'Lindqvist')

        columns = dict(_COLUMNS)
        row = next(s for s in self.report.get_result({})
                   if s.user_id == orphan.user_id)
        # Django's has_usable_password() answers True for an empty password, so
        # this column has to consult the raw field as well.
        self.assertEqual(columns['Has Password'](row), 'No')

    def test_student_with_a_password_is_flagged_as_having_one(self):
        from cis.reports.duplicate_students import _COLUMNS
        a = self._student('Priya', 'Raman')
        self._student('Priya', 'Raman')
        columns = dict(_COLUMNS)
        row = next(s for s in self.report.get_result({})
                   if s.user_id == a.user_id)
        self.assertEqual(columns['Has Password'](row), 'Yes')

    def test_every_column_renders_without_error(self):
        from django.utils.encoding import force_str
        from cis.reports.duplicate_students import _COLUMNS
        self._student('Rowan', 'Beaumont')
        self._student('Rowan', 'Beaumont')
        for record in self.report.get_result({}):
            for header, accessor in _COLUMNS:
                value = force_str(accessor(record))
                self.assertNotIn('bound method', value, msg=header)

    def test_registration_count_column_is_present(self):
        a = self._student('Theo', 'Vasquez')
        self._student('Theo', 'Vasquez')
        row = next(s for s in self.report.get_result({})
                   if s.user_id == a.user_id)
        self.assertEqual(row.n_reg, 0)
