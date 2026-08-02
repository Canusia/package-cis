"""The gaps standing between "a tenant spec exists" and "the spec is the live
student application", per Canusia/ewu#28 (which supersedes #27).

1. derived values have nowhere to live  -> tenant post_save hook
2. legacy-only writes in StudentProfileForm.save() that are cis model logic
   rather than tenant policy -> profile_last_reviewed, graduation_date/grade_level
3. cis's own tests must stay green once a tenant arms a spec
5. `disabled` is not expressible on a spec entry
"""
import datetime
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings

from cis.forms.application_fields import build_fields
from cis.forms.application_form import SpecDrivenApplicationForm
from cis.models.student import Student
from cis.utils import active_term

User = get_user_model()


def _sfx():
    return uuid.uuid4().hex[:8]


class DisabledFieldTests(TestCase):
    """Item 5. Django's `disabled` both greys the input and makes the field
    ignore any submitted value — the security half, which a widget attr alone
    does not give."""

    def test_disabled_reaches_the_field(self):
        field = dict(build_fields({
            'name': 'email', 'type': 'email', 'label': 'Email',
            'target': 'user', 'disabled': True,
        }))['email']
        self.assertTrue(field.disabled)

    def test_a_disabled_field_ignores_a_posted_value(self):
        spec = [{'name': 'email', 'type': 'email', 'label': 'Email',
                 'target': 'user', 'disabled': True,
                 'initial': 'verified@example.com'}]
        form = SpecDrivenApplicationForm(spec=spec, rules=[],
                                         data={'email': 'attacker@evil.com'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'verified@example.com')

    def test_fields_are_enabled_by_default(self):
        field = dict(build_fields({
            'name': 'email', 'type': 'email', 'label': 'Email',
            'target': 'user',
        }))['email']
        self.assertFalse(field.disabled)


class SpecIsolationTests(TestCase):
    """Item 3. An explicit `spec=` describes the whole form, so a tenant's real
    rules and validator must not leak into it. Without this, cis's own suite
    starts failing the day a tenant arms a spec."""

    def test_an_explicit_spec_does_not_pick_up_tenant_rules(self):
        def boom(form, cleaned_data):
            raise AssertionError('tenant validator leaked into an explicit spec')

        with self.settings(TABLE_CONFIGS_APP='cis.tests.fake_tenant'):
            form = SpecDrivenApplicationForm(
                spec=[{'name': 'first_name', 'type': 'text', 'label': 'First',
                       'target': 'user'}],
                data={'first_name': 'Ada'})
            self.assertEqual(form.rules, [])
            self.assertIsNone(form._tenant_validate)
            self.assertTrue(form.is_valid(), form.errors)

    def test_explicit_rules_still_win(self):
        form = SpecDrivenApplicationForm(
            spec=[
                {'name': 'a', 'type': 'text', 'label': 'A', 'target': 'meta'},
                {'name': 'b', 'type': 'text', 'label': 'B', 'target': 'meta'},
            ],
            rules=[{'rule': 'match', 'fields': ['a', 'b']}],
            data={'a': 'x', 'b': 'y'})
        self.assertFalse(form.is_valid())
        self.assertIn('b', form.errors)


class DerivedValueTests(TestCase):
    """Items 1 and 2."""

    def setUp(self):
        Group.objects.get_or_create(name='student')
        email = f'app-{_sfx()}@example.com'
        self.user = User.objects.create_user(username=email, email=email,
                                             password='x')
        self.student = Student.objects.create(user=self.user)

    def _save(self, spec, data, **kwargs):
        form = SpecDrivenApplicationForm(spec=spec, rules=[],
                                         student=self.student, data=data, **kwargs)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.user.refresh_from_db()
        self.student.refresh_from_db()
        return form

    # --- item 2: cis model logic, so the engine carries it ---------------

    def test_profile_last_reviewed_is_stamped(self):
        self._save([{'name': 'first_name', 'type': 'text', 'label': 'First',
                     'target': 'user'}], {'first_name': 'Ada'})
        self.assertEqual(self.student.profile_last_reviewed, active_term())

    def test_graduation_date_derives_grade_level(self):
        spec = [{'name': 'graduation_date', 'type': 'date', 'label': 'Grad',
                 'target': 'student'}]
        ahead = datetime.date.today() + datetime.timedelta(days=300)
        self._save(spec, {'graduation_date': ahead.isoformat()})

        expected = self.student.get_grade_level(graduation_date=ahead)
        valid = {c for c, _ in
                 self.student._meta.get_field('grade_level').choices if c}
        if expected in valid:
            self.assertEqual(self.student.grade_level, expected)

    def test_an_out_of_domain_grade_is_not_written(self):
        """get_grade_level returns sentinels ('GRAD', '--', None) that are not
        valid choices and would overflow the column."""
        spec = [{'name': 'graduation_date', 'type': 'date', 'label': 'Grad',
                 'target': 'student'}]
        self.student.grade_level = 'FR'
        self.student.save()
        long_past = datetime.date.today() - datetime.timedelta(days=4000)
        self._save(spec, {'graduation_date': long_past.isoformat()})

        valid = {c for c, _ in
                 self.student._meta.get_field('grade_level').choices if c}
        self.assertIn(self.student.grade_level, valid)

    def test_no_graduation_date_field_leaves_grade_level_alone(self):
        self.student.grade_level = 'SO'
        self.student.save()
        self._save([{'name': 'first_name', 'type': 'text', 'label': 'First',
                     'target': 'user'}], {'first_name': 'Ada'})
        self.assertEqual(self.student.grade_level, 'SO')

    # --- item 1: tenant post_save hook -----------------------------------

    def test_post_save_hook_runs_and_can_write_derived_values(self):
        """sccc's signed_no_ssn_waiver: a value derived from another field's
        answer, which no storage target can express."""
        calls = []

        def post_save(form, student, commit=True):
            calls.append(commit)
            if form.cleaned_data.get('no_ssn'):
                notifications = student.notifications or {}
                notifications['signed_no_ssn_waiver'] = True
                student.notifications = notifications

        spec = [{'name': 'no_ssn', 'type': 'agreement', 'label': 'No SSN',
                 'target': 'meta', 'required': False}]
        self._save(spec, {'no_ssn': 'on'}, post_save=post_save)

        self.assertEqual(self.student.notifications.get('signed_no_ssn_waiver'),
                         True)
        # it must run before the commit, or its writes are discarded
        self.assertEqual(calls, [False])

    def test_post_save_writes_survive_the_commit(self):
        def post_save(form, student, commit=True):
            student.grade_level = 'JR'

        spec = [{'name': 'first_name', 'type': 'text', 'label': 'First',
                 'target': 'user'}]
        self._save(spec, {'first_name': 'Ada'}, post_save=post_save)
        self.assertEqual(self.student.grade_level, 'JR')

    def test_post_save_can_touch_the_user(self):
        def post_save(form, student, commit=True):
            student.user.last_name = 'Lovelace'

        spec = [{'name': 'first_name', 'type': 'text', 'label': 'First',
                 'target': 'user'}]
        self._save(spec, {'first_name': 'Ada'}, post_save=post_save)
        self.assertEqual(self.user.last_name, 'Lovelace')

    def test_no_hook_is_fine(self):
        self._save([{'name': 'first_name', 'type': 'text', 'label': 'First',
                     'target': 'user'}], {'first_name': 'Ada'})
        self.assertEqual(self.user.first_name, 'Ada')

    def test_post_save_runs_before_the_dirty_check(self):
        """A tenant write to a tracked field must count as a change."""
        def post_save(form, student, commit=True):
            student.user.first_name = 'Changed By Hook'

        self.user.last_name = 'Lovelace'
        self.user.save()
        request = RequestFactory().post('/')
        request.user = self.user
        # the posted field itself is unchanged — only the hook's write differs
        self._save([{'name': 'last_name', 'type': 'text', 'label': 'Last',
                     'target': 'user'}], {'last_name': 'Lovelace'},
                   request=request, post_save=post_save)
        self.assertIsNotNone(self.student.profile_dirty_at)


class SettingsVocabularyTests(TestCase):
    """Item 4. The profile-fields settings table takes its vocabulary from the
    legacy form, so a field existing only in a spec gets no row, no
    configurable label and no seeded weight."""

    SPEC = [
        {'name': 'first_name', 'type': 'text', 'label': 'First', 'target': 'user'},
        {'name': 'tribal_affiliation', 'type': 'text', 'label': 'Tribe',
         'target': 'meta'},
    ]

    def test_spec_only_fields_join_the_profile_vocabulary(self):
        from cis.settings.student_profile import profile_field_names

        with self.settings(TABLE_CONFIGS_APP='cis.tests.fake_tenant'):
            names = profile_field_names(spec=self.SPEC)
        self.assertIn('tribal_affiliation', names)
        # and the legacy vocabulary is preserved
        self.assertIn('first_name', names)
        self.assertIn('cell_phone', names)

    def test_no_spec_leaves_the_vocabulary_untouched(self):
        from cis.settings.student_profile import profile_fields, profile_field_names

        self.assertEqual(profile_field_names(), profile_fields())

    def test_spec_only_fields_get_a_seeded_weight(self):
        from cis.settings.student_profile import default_field_weights

        weights = default_field_weights(spec=self.SPEC)
        self.assertIn('tribal_affiliation', weights)
        self.assertIsInstance(weights['tribal_affiliation'], int)

    def test_signup_mechanics_stay_out_of_the_editable_vocabulary(self):
        from cis.settings.student_profile import profile_field_names

        spec = self.SPEC + [{'name': 'password', 'type': 'password_pair',
                             'label': 'Password', 'target': 'skip'}]
        self.assertNotIn('password', profile_field_names(spec=spec))


@override_settings(TABLE_CONFIGS_APP='cis.tests.fake_tenant')
class ArmedTenantTests(TestCase):
    """Item 3, made permanent.

    `cis.tests.fake_tenant` is a stand-in for a tenant that has ARMED a spec —
    it exports fields, rules, VALIDATE_FIELDS, validate() and post_save(). The
    assertions below are the ones that used to hold only because no tenant had
    a spec; they must survive the day one does, which is the whole definition
    of done on #28.
    """

    def setUp(self):
        Group.objects.get_or_create(name='student')
        email = f'armed-{_sfx()}@example.com'
        self.user = User.objects.create_user(username=email, email=email,
                                             password='x')
        self.student = Student.objects.create(user=self.user)

    def test_the_tenant_spec_is_actually_visible(self):
        """Guard the guard: if this fails the others prove nothing."""
        from cis.forms.application_spec import (
            get_application_fields, get_application_rules,
            get_tenant_post_save, get_tenant_validator)

        self.assertEqual([e['name'] for e in get_application_fields()],
                         ['first_name', 'tribal_affiliation', 'no_ssn'])
        self.assertEqual(get_application_rules()[0]['rule'], 'fields_must_differ')
        validate, owned = get_tenant_validator()
        self.assertIsNotNone(validate)
        self.assertEqual(owned, frozenset({'tribal_affiliation'}))
        self.assertIsNotNone(get_tenant_post_save())

    def test_an_explicit_spec_still_ignores_the_tenants_rules(self):
        form = SpecDrivenApplicationForm(
            spec=[{'name': 'first_name', 'type': 'text', 'label': 'First',
                   'target': 'user'}],
            student=self.student, data={'first_name': 'Ada'})
        self.assertEqual(form.rules, [])
        self.assertIsNone(form._tenant_validate)
        self.assertIsNone(form._tenant_post_save)
        self.assertTrue(form.is_valid(), form.errors)

    def test_an_explicit_spec_still_routes_meta_values(self):
        form = SpecDrivenApplicationForm(
            spec=[{'name': 'nickname', 'type': 'text', 'label': 'Nickname',
                   'required': False, 'target': 'meta'}],
            student=self.student, data={'nickname': 'Robbie'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.save(), self.student)
        self.student.refresh_from_db()
        self.assertEqual(self.student.meta['nickname'], 'Robbie')

    def test_an_explicit_spec_still_sanitizes(self):
        form = SpecDrivenApplicationForm(
            spec=[{'name': 'nickname', 'type': 'text', 'label': 'Nickname',
                   'required': False, 'target': 'meta'}],
            student=self.student,
            data={'nickname': '<script>alert(1)</script>Robbie'})
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.student.refresh_from_db()
        self.assertNotIn('<script>', self.student.meta['nickname'])
        self.assertIn('Robbie', self.student.meta['nickname'])

    # --- and the self-configuring form does pick the tenant up -----------

    def test_the_self_configuring_form_uses_the_tenant_config_end_to_end(self):
        from cis.forms.application_form import get_application_form

        form = get_application_form(student=self.student,
                                    data={'first_name': 'ada',
                                          'no_ssn': 'on'})
        self.assertTrue(form.is_valid(), form.errors)
        # the tenant's validators normalise
        self.assertEqual(form.cleaned_data['first_name'], 'Ada')
        form.save()
        self.student.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Ada')
        # ...and the tenant's post_save wrote the derived value
        self.assertEqual(self.student.notifications.get('signed_no_ssn_waiver'),
                         True)

    def test_the_tenant_validator_displaces_the_shared_rule_it_owns(self):
        from cis.forms.application_form import get_application_form

        # fields_must_differ covers tribal_affiliation, which VALIDATE_FIELDS
        # claims — so equal values must NOT raise the shared rule's error.
        form = get_application_form(student=self.student,
                                    data={'first_name': 'Ada',
                                          'tribal_affiliation': 'Ada'})
        self.assertTrue(form.is_valid(), form.errors)
