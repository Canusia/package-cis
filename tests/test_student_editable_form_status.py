"""StudentEditableForm status gating against cis.tests.fake_tenant
(package-cis#57). EditableProfileMixin is cis policy; the fields it gates are
the fake tenant's, so these hold on every tenant."""
import uuid

from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from cis.forms import student_profile as profile_mod
from cis.models.customuser import CustomUser
from cis.models.highschool import HighSchool
from cis.models.settings import Setting
from cis.models.student import Student
from cis.settings.student_profile import profile_fields, student_profile

FAKE_TENANT = 'cis.tests.fake_tenant'


def _form(*args, **kwargs):
    return profile_mod.StudentEditableForm(*args, **kwargs)


def _make_student(status, sent_to_sis=False, highschool=None):
    user = CustomUser.objects.create(
        username=f'u-{uuid.uuid4()}',
        email=f'{uuid.uuid4()}@example.com',
        first_name='Test',
        last_name='User',
        psid='-',
    )
    student = Student.objects.create(
        user=user, meta={'fake_meta_note': 'on file'}, highschool=highschool)
    updates = {'application_status': status}
    if sent_to_sis:
        updates['sis_sent_on'] = timezone.now()
    # update() bypasses the application-status signals.
    Student.objects.filter(pk=student.pk).update(**updates)
    student.refresh_from_db()
    return student


def _editable(form):
    """Field names the student can actually change: gated fields are rendered
    read-only rather than dropped."""
    return {n for n in form.fields if n not in form.readonly_fields}


def _set_editable(fields):
    Setting.objects.update_or_create(
        key=student_profile.key,
        defaults={'value': {
            'editable_fields': fields,
            'locked_message': 'locked',
            'editable_message': 'editable',
            'profile_review_intro': 'intro',
            'profile_review_template': '<div></div>',
        }},
    )


@override_settings(TENANT_SERVICES_APP=FAKE_TENANT)
class StudentEditableFormStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Group.objects.get_or_create(name='student')
        cls.hs = HighSchool.objects.create(
            name='Gate Test High School', code='GTHS', status='Active')
        CustomUser.objects.get_or_create(
            username='cron', defaults={'email': 'cron@example.com'})
        _set_editable(['fake_meta_note', 'email'])

    def test_pending_student_can_edit_application_fields_only(self):
        form = _form(student=_make_student('pending'))
        self.assertEqual(form.readonly_fields, set())
        for name in ('first_name', 'ssn', 'fake_color', 'fake_meta_note',
                     'fake_attestation'):
            self.assertIn(name, form.fields, f'{name} should be editable')
        for name in ('password', 'confirm_password', 'signature'):
            self.assertNotIn(name, form.fields)
        self.assertTrue(set(form.fields).issubset(set(profile_fields())))

    def test_accepted_student_restricted_to_setting_fields(self):
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertEqual(_editable(form), {'fake_meta_note', 'email'})
        for gated in ('fake_color', 'first_name'):
            self.assertIn(gated, form.fields, gated)
            self.assertIn(gated, form.readonly_fields, gated)

    def test_accepted_student_with_empty_editable_fields_has_no_fields(self):
        # An explicit empty list means nothing is editable when accepted —
        # it must NOT silently fall back to EDITABLE_FIELDS.
        _set_editable([])
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertEqual(_editable(form), set())
        self.assertTrue(form.fields)

    def test_accepted_pre_sis_student_gets_only_configured_fields(self):
        """Being pre-SIS does not widen the admin-configured set."""
        form = _form(student=_make_student('accepted', sent_to_sis=False))
        self.assertEqual(_editable(form), {'fake_meta_note', 'email'})
        for identity in ('first_name', 'last_name', 'date_of_birth'):
            self.assertIn(identity, form.readonly_fields, identity)
        self.assertNotIn('ssn', form.fields)

    def test_accepted_gating_is_the_same_pre_and_post_sis(self):
        pre = _form(student=_make_student('accepted', sent_to_sis=False))
        post = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertEqual(_editable(pre), _editable(post))
        self.assertEqual(pre.readonly_fields, post.readonly_fields)

    def test_gated_fields_are_shown_read_only_not_removed(self):
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertFalse(form.fields['fake_meta_note'].disabled)
        self.assertNotIn('fake_meta_note', form.readonly_fields)
        for name in ('fake_color', 'date_of_birth'):
            self.assertIn(name, form.fields, name)
            self.assertTrue(form.fields[name].disabled, name)
            self.assertIn(name, form.readonly_fields, name)

    def test_ssn_is_hidden_rather_than_shown_read_only(self):
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertNotIn('ssn', form.fields)
        self.assertNotIn('verify_student_ssn', form.fields)

    def test_signup_mechanics_stay_hidden_not_read_only(self):
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        for name in ('password', 'confirm_password', 'signature'):
            self.assertNotIn(name, form.fields, name)

    def test_read_only_fields_are_never_required(self):
        """Django enforces `required` on disabled fields using `initial`, so a
        required gated field with no stored value (fake_color here) would make
        the form permanently unsubmittable."""
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertIn('fake_color', form.readonly_fields)
        still_required = [n for n in form.readonly_fields
                          if form.fields[n].required]
        self.assertEqual(still_required, [])

    def test_errors_on_read_only_fields_do_not_block_submission(self):
        """The fake tenant's clean() requires fake_other_color whenever
        fake_color is blank or 'other'. Both are gated read-only here and the
        record has neither, so without discarding gated-field errors the
        student could never save."""
        student = _make_student('accepted', sent_to_sis=True, highschool=self.hs)
        form = _form(student, None, {
            'fake_meta_note': 'updated',
            'email': student.user.email,
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        self.assertNotIn('fake_other_color', form.errors)

    def test_cross_field_rule_still_applies_when_its_fields_are_editable(self):
        _set_editable(['fake_color', 'fake_other_color', 'email'])
        student = _make_student('accepted', sent_to_sis=True, highschool=self.hs)
        form = _form(student, None, {
            'fake_color': 'other',
            'email': student.user.email,
        })
        self.assertFalse(form.is_valid())
        self.assertIn('fake_other_color', form.errors)

    def test_in_review_hides_ssn_and_locks_everything_else(self):
        form = _form(student=_make_student('in_review'))
        self.assertNotIn('ssn', form.fields)
        self.assertNotIn('verify_student_ssn', form.fields)
        self.assertTrue(form.fields)
        self.assertTrue(all(f.disabled for f in form.fields.values()))

    def test_posted_value_for_a_read_only_field_is_not_persisted(self):
        """A gated field cannot be written, even by a hand-crafted POST."""
        student = _make_student('accepted', sent_to_sis=True, highschool=self.hs)
        form = _form(student, None, {
            'fake_meta_note': 'updated',
            'email': student.user.email,
            'first_name': 'HACKED',
            'fake_color': 'green',
        })
        self.assertTrue(form.is_valid(), form.errors.as_json())
        form.save(student)
        student.refresh_from_db()
        student.user.refresh_from_db()
        self.assertEqual(student.user.first_name, 'Test')
        self.assertNotIn('fake_color', student.meta)
        self.assertEqual(student.meta['fake_meta_note'], 'updated')

    def test_accepted_student_with_no_setting_row_falls_back_to_tenant_default(self):
        # No student_profile Setting row: editable_fields is None (not []),
        # which falls back to the tenant's EDITABLE_FIELDS — whose undeclared
        # entry (fake_not_declared) is inert.
        Setting.objects.filter(key=student_profile.key).delete()
        form = _form(student=_make_student('accepted', sent_to_sis=True))
        self.assertEqual(profile_mod.tenant_editable_fields(),
                         ('email', 'fake_meta_note', 'fake_not_declared'))
        self.assertEqual(_editable(form), {'email', 'fake_meta_note'})
        self.assertNotEqual(_editable(form), set(profile_fields()))

    def test_in_review_student_auto_locks_all_fields(self):
        form = _form(student=_make_student('in_review'))
        self.assertTrue(form.fields)
        self.assertTrue(set(form.fields).issubset(set(profile_fields())))
        for name, field in form.fields.items():
            self.assertTrue(field.disabled, f'{name} should be disabled')
