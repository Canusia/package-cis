import uuid

from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from cis.forms.student_profile import StudentEditableForm, tenant_editable_fields
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.settings import Setting
from cis.models.student import Student
from cis.settings.student_profile import profile_fields, student_profile


def _make_student(status, sent_to_sis=False, highschool=None):
    user = CustomUser.objects.create(
        username=f'u-{uuid.uuid4()}',
        email=f'{uuid.uuid4()}@example.com',
        first_name='Test',
        last_name='User',
        psid='-',
    )
    student = Student.objects.create(user=user, meta={}, highschool=highschool)
    updates = {'application_status': status}
    if sent_to_sis:
        updates['sis_sent_on'] = timezone.now()
    # update() bypasses the application-status signals.
    Student.objects.filter(pk=student.pk).update(**updates)
    student.refresh_from_db()
    return student


def _editable(form):
    """Field names the student can actually change.

    Gated fields are now rendered read-only rather than dropped, so
    `form.fields` is no longer the answer to "what may be edited" — the
    difference between it and `form.readonly_fields` is.
    """
    return {n for n in form.fields if n not in form.readonly_fields}


class StudentEditableFormStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(
            name='Gate Test High School', code='GTHS', status='Active')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {
                'editable_fields': ['cell_phone', 'email'],
                'locked_message': 'locked',
                'editable_message': 'editable',
                'profile_review_intro': 'intro',
                'profile_review_template': '<div></div>',
            }},
        )

    def test_pending_student_can_edit_application_fields_only(self):
        student = _make_student('pending')
        form = StudentEditableForm(student=student)
        # The student-profile application fields are editable while pending.
        self.assertEqual(form.readonly_fields, set())
        for name in ('first_name', 'ssn', 'graduation_date',
                     'mailing_address', 'parent_email', 'cte'):
            self.assertIn(name, form.fields, f'{name} should be editable')
        # Signup mechanics are never exposed.
        self.assertNotIn('password', form.fields)
        self.assertNotIn('confirm_password', form.fields)
        self.assertNotIn('signature', form.fields)
        # Nothing outside the student-profile field set leaks in.
        self.assertTrue(set(form.fields).issubset(set(profile_fields())))

    def test_accepted_student_restricted_to_setting_fields(self):
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        self.assertEqual(_editable(form), {'cell_phone', 'email'})
        # Still rendered, just not editable.
        for gated in ('graduation_date', 'first_name'):
            self.assertIn(gated, form.fields, gated)
            self.assertIn(gated, form.readonly_fields, gated)

    def test_accepted_student_with_empty_editable_fields_has_no_fields(self):
        # An explicit empty list means nothing is editable when accepted —
        # it must NOT silently fall back to EDITABLE_FIELDS.
        Setting.objects.update_or_create(
            key=student_profile.key,
            defaults={'value': {
                'editable_fields': [],
                'locked_message': '',
                'editable_message': '',
                'profile_review_intro': '',
                'profile_review_template': '<div></div>',
            }},
        )
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        # Nothing editable — but the record is still shown, read-only.
        self.assertEqual(_editable(form), set())
        self.assertTrue(form.fields)

    def test_accepted_pre_sis_student_gets_only_configured_fields(self):
        """Being pre-SIS does not widen the admin-configured set.

        This used to append first_name / last_name / date_of_birth / ssn for a
        student whose record had not reached the SIS, which silently overrode
        the admin's decision to exclude them — an accepted student showed 32
        fields where 29 were configured. The configured list is now the only
        authority for `accepted`, whether or not the record has been sent.
        """
        student = _make_student('accepted', sent_to_sis=False)
        form = StudentEditableForm(student=student)
        self.assertEqual(_editable(form), {'cell_phone', 'email'})
        for identity in ('first_name', 'last_name', 'date_of_birth'):
            self.assertIn(identity, form.readonly_fields, identity)
        self.assertNotIn('ssn', form.fields)

    def test_accepted_gating_is_the_same_pre_and_post_sis(self):
        """The two paths must not diverge again."""
        pre = StudentEditableForm(student=_make_student('accepted', sent_to_sis=False))
        post = StudentEditableForm(student=_make_student('accepted', sent_to_sis=True))
        self.assertEqual(_editable(pre), _editable(post))
        self.assertEqual(pre.readonly_fields, post.readonly_fields)

    # ------------------------------------------------------------------
    # Gated fields are DISPLAYED read-only rather than dropped, so a
    # student can see the values on file without being able to change them.
    # ------------------------------------------------------------------

    def test_gated_fields_are_shown_read_only_not_removed(self):
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        # Configured editable stays editable. (`email` is NOT a useful probe
        # here — the tenant form declares it disabled=True in its own field
        # definition, independent of this gate.)
        self.assertFalse(form.fields['cell_phone'].disabled)
        self.assertNotIn('cell_phone', form.readonly_fields)
        # Not configured: still rendered, but read-only.
        for name in ('city', 'graduation_date'):
            self.assertIn(name, form.fields, name)
            self.assertTrue(form.fields[name].disabled, name)
            self.assertIn(name, form.readonly_fields, name)

    def test_ssn_is_hidden_rather_than_shown_read_only(self):
        """SSN is never rendered when it is not editable — not even disabled.

        A read-only SSN would put the number on the page for anyone shoulder-
        surfing, and its verify half has no stored value so it would render as
        an empty 'Re-enter SSN' box.
        """
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        self.assertNotIn('ssn', form.fields)
        self.assertNotIn('verify_student_ssn', form.fields)

    def test_signup_mechanics_stay_hidden_not_read_only(self):
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        for name in ('password', 'confirm_password', 'signature'):
            self.assertNotIn(name, form.fields, name)

    def test_read_only_fields_are_never_required(self):
        """A field the student cannot edit must not block their submission.

        Django enforces `required` on disabled fields using `initial`, so a
        required gated field with no stored value would make the form
        permanently unsubmittable.
        """
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        self.assertTrue(form.readonly_fields)
        still_required = [n for n in form.readonly_fields
                          if form.fields[n].required]
        self.assertEqual(still_required, [])

    def test_errors_on_read_only_fields_do_not_block_submission(self):
        """clean() validates cross-field rules over the whole form, including
        gated fields. An error on a field the student cannot edit is not
        actionable, so it must not make the form permanently unsubmittable.

        Concretely: the tenant clean() requires mailing_city/state/zip whenever
        same_as_permanent is falsy. Those are gated read-only here and the
        record has none of them, so without this the student could never save.
        """
        student = _make_student('accepted', sent_to_sis=True, highschool=self.hs)
        form = StudentEditableForm(student, None, {
            'cell_phone': '5095551234',
            'email': student.user.email,
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        for gated in ('mailing_city', 'mailing_state', 'mailing_zip_code'):
            self.assertNotIn(gated, form.errors, gated)

    def test_in_review_hides_ssn_and_locks_everything_else(self):
        student = _make_student('in_review')
        form = StudentEditableForm(student=student)
        self.assertNotIn('ssn', form.fields)
        self.assertNotIn('verify_student_ssn', form.fields)
        self.assertTrue(form.fields)
        self.assertTrue(all(f.disabled for f in form.fields.values()))

    def test_posted_value_for_a_read_only_field_is_not_persisted(self):
        """The security property the old delete-the-field approach gave us for
        free: a gated field cannot be written, even by a hand-crafted POST."""
        student = _make_student('accepted', sent_to_sis=True, highschool=self.hs)
        form = StudentEditableForm(student, None, {
            'cell_phone': '5095551234',
            'email': student.user.email,
            'first_name': 'HACKED',
            'city': 'HACKEDVILLE',
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save(student)
        student.user.refresh_from_db()
        self.assertEqual(student.user.first_name, 'Test')
        self.assertNotEqual(student.user.city, 'HACKEDVILLE')

    def test_accepted_student_with_no_setting_row_falls_back_to_tenant_default(self):
        # Fail-open direction: no student_profile Setting row at all means
        # config.get('editable_fields') is None (not []), which must fall
        # back to the tenant's own default rather than the full profile set.
        Setting.objects.filter(key=student_profile.key).delete()
        student = _make_student('accepted', sent_to_sis=True)
        form = StudentEditableForm(student=student)
        # tenant_editable_fields() carries some names that aren't declared
        # StudentProfileForm fields (see Trap 1 in the tenant-relocation
        # propagation plan) — intersect with profile_fields() the same way
        # the form itself effectively does.
        expected = set(profile_fields()) & set(tenant_editable_fields())
        self.assertEqual(_editable(form), expected)
        self.assertNotEqual(_editable(form), set(profile_fields()))

    def test_in_review_student_auto_locks_all_fields(self):
        # in_review auto-locks even when the caller omits is_locked.
        student = _make_student('in_review')
        form = StudentEditableForm(student=student)
        self.assertTrue(form.fields)
        self.assertTrue(set(form.fields).issubset(set(profile_fields())))
        for name, field in form.fields.items():
            self.assertTrue(field.disabled, f'{name} should be disabled')
