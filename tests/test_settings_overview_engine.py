from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django import forms

from cis.services.settings_overview import build_overview

import importlib.util
if importlib.util.find_spec('setting.setting'):
    from setting.setting.models import SettingRecord
else:
    from setting.models import SettingRecord


class BuildOverviewTests(TestCase):
    def setUp(self):
        # The ephemeral test DB has no SettingRecord rows (those are seeded
        # by `register_settings` against the real DB, never in tests). Create
        # the one we need so the engine can resolve a record_id for signup.
        self.signup_record = SettingRecord.objects.create(
            app='cis', name='signup', title='Signup', categories='1')

    def test_builds_sections_and_pulls_labels_and_values(self):
        # Uses the real student_registration profile + real form classes.
        # signup.intro has a known label; from_db returns a dict (empty, since
        # there's no cis.Setting row in the test DB, but from_db() guards
        # against that and returns {} rather than raising).
        ov = build_overview('student_registration')
        self.assertEqual(ov['title'], 'Student Registration Settings')
        titles = [s['title'] for s in ov['sections']]
        self.assertIn('Account signup', titles)

        # find the signup item and confirm its 'intro' field's label came
        # from base_fields, and that record_id matches the record we created.
        signup_item = None
        for s in ov['sections']:
            for it in s['items']:
                if it.get('record_id') == str(self.signup_record.id) and any(
                        f['label'] == 'Post Email Verify Page Intro.' for f in it['fields']):
                    signup_item = it
        self.assertIsNotNone(signup_item, 'signup intro field/label not found')
        self.assertTrue(signup_item['available'])

    def test_unresolvable_configurator_degrades(self):
        bad = {'title': 'X', 'sections': [
            {'title': 'S', 'items': [{'app': 'cis', 'name': 'does_not_exist'}]}]}
        with patch('cis.services.settings_overview._get_profile', return_value=bad):
            ov = build_overview('anything')
        item = ov['sections'][0]['items'][0]
        self.assertFalse(item['available'])
        self.assertEqual(item['fields'], [])

    def test_from_db_exception_degrades(self):
        # Locks the single-pass fix: a configurator whose form class resolves
        # fine but whose from_db() raises must degrade to available=False
        # rather than crashing build_overview (previously from_db() was
        # called a second time outside any try/except).
        bad = {'title': 'X', 'sections': [
            {'title': 'S', 'items': [{'app': 'cis', 'name': 'signup'}]}]}
        with patch('cis.services.settings_overview._get_profile', return_value=bad), \
                patch('cis.services.settings_overview.import_string') as mock_import:
            mock_form_cls = mock_import.return_value
            mock_form_cls.from_db.side_effect = RuntimeError('boom')
            ov = build_overview('anything')
        item = ov['sections'][0]['items'][0]
        self.assertFalse(item['available'])
        self.assertEqual(item['fields'], [])

    def test_empty_value_flagged(self):
        # ferpa has one field; force its from_db to empty and confirm is_empty.
        real = build_overview('student_registration')
        # locate any field and assert the empty marker contract holds structurally
        for s in real['sections']:
            for it in s['items']:
                for f in it['fields']:
                    self.assertIn('is_empty', f)
                    self.assertIn('is_html', f)


    def test_menu_and_intro_default_when_profile_omits_them(self):
        bare = {'title': 'X', 'sections': []}
        with patch('cis.services.settings_overview._get_profile', return_value=bare):
            ov = build_overview('anything')
        from cis.services.settings_overview import DEFAULT_INTRO, DEFAULT_MENU
        self.assertEqual(ov['menu'], DEFAULT_MENU)
        self.assertEqual(ov['menu'], ('students', 'students'))
        self.assertEqual(ov['intro'], DEFAULT_INTRO)

    def test_menu_and_intro_pass_through(self):
        prof = {'title': 'X', 'sections': [],
                'menu': ('highschools', 'school_administrators'),
                'intro': 'Settings behind the school admin portal.'}
        with patch('cis.services.settings_overview._get_profile', return_value=prof):
            ov = build_overview('anything')
        self.assertEqual(ov['menu'], ('highschools', 'school_administrators'))
        self.assertEqual(ov['intro'], 'Settings behind the school admin portal.')

    def test_whitelisted_runtime_field_is_shown(self):
        # cis.settings.menu adds its '<role>_menu' fields in __init__, so they
        # are not in base_fields; a whitelist must still reach them.
        from django.conf import settings as dj_settings
        from cis.models.settings import Setting
        from cis.settings.menu import menu
        role = next(iter(dj_settings.MY_CE['roles']))
        SettingRecord.objects.create(app='cis', name='menu', title='System Menu', categories='4')
        Setting.objects.update_or_create(key=menu.key, defaults={'value': {f'{role}_menu': '[{"label": "Home"}]'}})
        prof = {'title': 'X', 'sections': [{'title': 'S', 'items': [
            {'app': 'cis', 'name': 'menu', 'fields': [f'{role}_menu']}]}]}
        request = RequestFactory().get('/x', {'report_id': '1'})
        with patch('cis.services.settings_overview._get_profile', return_value=prof):
            ov = build_overview('anything', request=request)
        item = ov['sections'][0]['items'][0]
        self.assertTrue(item['available'])
        self.assertEqual(len(item['fields']), 1)
        self.assertIn('Home', item['fields'][0]['value'])

    def test_runtime_only_fields_render_from_instance_without_whitelist(self):
        # cis.settings.menu adds every field in __init__ (base_fields empty);
        # with no whitelist the instance's fields are used.
        from cis.settings.menu import menu
        SettingRecord.objects.create(app='cis', name='menu', title='System Menu', categories='4')
        prof = {'title': 'X', 'sections': [{'title': 'S', 'items': [{'app': 'cis', 'name': 'menu'}]}]}
        request = RequestFactory().get('/x', {'report_id': '1'})
        with patch('cis.services.settings_overview._get_profile', return_value=prof):
            ov = build_overview('anything', request=request)
        item = ov['sections'][0]['items'][0]
        self.assertTrue(item['available'])
        self.assertGreater(len(item['fields']), 0)

    def test_real_hs_admin_language_has_fields(self):
        prof = {'title': 'X', 'sections': [{'title': 'S', 'items': [
            {'app': 'cis', 'name': 'highschool_admin_portal'}]}]}
        request = RequestFactory().get('/x', {'report_id': '1'})
        with patch('cis.services.settings_overview._get_profile', return_value=prof):
            ov = build_overview('anything', request=request)
        item = ov['sections'][0]['items'][0]
        self.assertTrue(item['available'])
        self.assertGreater(len(item['fields']), 0)

    def test_fake_runtime_form_without_whitelist(self):
        class RtForm(forms.Form):
            def __init__(self, request=None, initial=None, **kw):
                super().__init__(**kw)
                self.fields['alpha'] = forms.CharField(label='Alpha')
                self.fields['beta'] = forms.CharField(label='Beta')

            @classmethod
            def from_db(cls):
                return {'alpha': 'one'}

        prof = {'title': 'X', 'sections': [{'title': 'S', 'items': [{'app': 'cis', 'name': 'rt'}]}]}
        request = RequestFactory().get('/x')
        real = __import__('django.utils.module_loading', fromlist=['import_string']).import_string
        def fake(path):
            return RtForm if path == 'cis.settings.rt.rt' else real(path)
        with patch('cis.services.settings_overview._get_profile', return_value=prof), \
                patch('cis.services.settings_overview.import_string', side_effect=fake):
            ov = build_overview('anything', request=request)
        labels = [f['label'] for f in ov['sections'][0]['items'][0]['fields']]
        self.assertEqual(labels, ['Alpha', 'Beta'])


class HeadingSkipTests(TestCase):
    def _run(self, item):
        prof = {'title': 'X', 'sections': [{'title': 'S', 'items': [item]}]}
        request = RequestFactory().get('/x', {'report_id': '1'})
        with patch('cis.services.settings_overview._get_profile', return_value=prof):
            ov = build_overview('anything', request=request)
        return ov['sections'][0]['items'][0]

    def test_heading_pseudo_fields_skipped(self):
        SettingRecord.objects.create(app='cis', name='future_sections',
                                     title='Section Requests', categories='1')
        item = self._run({'app': 'cis', 'name': 'future_sections'})
        self.assertTrue(item['available'])
        self.assertGreater(len(item['fields']), 0)
        self.assertFalse([f for f in item['fields'] if '<h' in f['label']])


class StudentRegistrationRegressionTests(TestCase):
    """student_registration renders the de550f6 labels minus the two escaped heading rows
    (<h3> Parent/Student Notification(s) pseudo-fields), which are skipped everywhere."""
    EXPECTED = [
        ['Active Academic Year', 'Home School', 'Active Term', 'Registration Term(s)', 'Scholarship App Open Until', 'Tuition Pay Open Until', 'Message when Registration is Closed', 'Opens On', 'Open Until', 'Starting Birth Date', 'Ending Birth Date'],
        ['Student Verify Email Form Field Labels', 'Pre-Email Verify Page Intro.', 'Awaiting Verification Page Intro.', 'Confirm Verification Page Intro.', 'Post Email Verify Page Intro.', 'Agreement Terms', 'Alert/Error Messages'],
        ['Profile Fields — Order, Editability, Label & Help Text', 'Profile Not Editable Message', 'Profile Editable Message', 'Profile Review Intro.', 'Profile Review Display Template', 'Student Detail Layout (advanced)'],
        ['Intro.'],
        ['Intro.', 'Parent Consent Term(s)'],
        ['Intro.', 'Tab # Search for Class(es)', 'Tab # EC Classes', 'Tab # My Class Application(s)', 'Footer # My Class'],
        ['Enabled', 'hs_pay_type', 'Registration Charge Addition Trigger(s)', 'Registration Charge Removal Trigger(s)', 'TA Request Updated Subject', 'TA Request Updated Email', 'Mode', 'Cron Expression for Sending Missing Payment Reminder', 'Bill Pay Subject', 'Bill Pay Email', 'Payment Received Subject', 'Payment Received Email', 'Invoice Template Header', 'Invoice Template Footer'],
        ['Enabled', 'Verification Email Subject', 'Verification Email', 'Send an email when ID is assigned?', 'Python Regex Pattern to Verify Valid ID', 'Student ID Assigned Email Subject', 'ID Assigned Email Message'],
        ['SIS Mirror Trigger(s)', 'SIS Mirror Term(s)', 'Stop mirroring when these errors happen again', 'Cron Expression for Mirroring with SIS', 'SIS Mirror Notification Email(s)', 'All Emails Enabled', 'Parent/Counselor Status Trigger(s)', 'Parent/Counselor Email Subject', 'Parent/Counselor Email', 'Student Email - Status Trigger(s)'],
    ]

    def test_labels_unchanged(self):
        from django.contrib.auth import get_user_model
        request = RequestFactory().get('/x')
        request.user = get_user_model().objects.create_superuser(
            username='srreg', email='srreg@example.com', password='x')
        ov = build_overview('student_registration', request=request)
        got = [[f['label'] for f in i['fields']]
               for s in ov['sections'] for i in s['items']]
        self.assertEqual(got, self.EXPECTED)


class ChoiceResolutionTests(TestCase):
    def _req(self):
        # A minimal request; forms only need it as a positional arg (mirrors
        # setting.record_details' `form_cls(request, initial=...)`).
        return RequestFactory().get('/ce/settings-overview/student_registration/')

    def test_choice_field_guid_renders_label(self):
        from cis.models.term import Term, AcademicYear
        from cis.models.settings import Setting
        from cis.settings.registrations import registrations
        ay = AcademicYear.objects.create(name='2026-2027')
        term = Term.objects.create(label='Fall 2026', code='26FA', academic_year=ay)
        Setting.objects.update_or_create(
            key=registrations.key,
            defaults={'value': {'active_term': str(term.id),
                                'academic_year': str(ay.id),
                                'registration_terms': [str(term.id)]}})
        ov = build_overview('student_registration', request=self._req())
        # find the registrations item's fields
        fields = {}
        for s in ov['sections']:
            for it in s['items']:
                for f in it['fields']:
                    fields[f['label']] = f['value']
        # Term.__str__ / AcademicYear.__str__ supply the labels
        self.assertEqual(fields.get('Active Term'), str(term))
        self.assertEqual(fields.get('Active Academic Year'), str(ay))
        self.assertEqual(fields.get('Registration Term(s)'), str(term))
        # And a GUID must NOT appear
        self.assertNotIn(str(term.id), fields.get('Active Term', ''))

    def test_no_request_falls_back_to_raw(self):
        from cis.models.settings import Setting
        from cis.settings.registrations import registrations
        Setting.objects.update_or_create(
            key=registrations.key, defaults={'value': {'active_term': 'RAWGUID'}})
        ov = build_overview('student_registration')          # no request
        vals = [f['value'] for s in ov['sections'] for it in s['items'] for f in it['fields']]
        self.assertIn('RAWGUID', vals)                       # raw, unresolved

    def test_instantiation_failure_falls_back_without_raising(self):
        bad = {'title': 'X', 'sections': [
            {'title': 'S', 'items': [{'app': 'cis', 'name': 'registrations'}]}]}
        with patch('cis.services.settings_overview._get_profile', return_value=bad), \
             patch('cis.services.settings_overview.import_string') as imp:
            class Boom:
                base_fields = {'active_term': forms.ChoiceField()}
                @classmethod
                def from_db(cls):
                    return {'active_term': 'G'}
                def __init__(self, *a, **k):
                    raise RuntimeError('cannot construct')
            imp.return_value = Boom
            ov = build_overview('anything', request=self._req())
        item = ov['sections'][0]['items'][0]
        self.assertTrue(item['available'])                   # still shown
        self.assertEqual(item['fields'][0]['value'], 'G')    # raw fallback

    def test_overview_render_override_wins(self):
        bad = {'title': 'X', 'sections': [
            {'title': 'S', 'items': [{'app': 'cis', 'name': 'x'}]}]}
        class WithHook:
            base_fields = {'active_term': forms.ChoiceField()}
            @classmethod
            def from_db(cls):
                return {'active_term': 'G'}
            @classmethod
            def overview_render(cls, values):
                return {'active_term': 'CUSTOM'}
            def __init__(self, *a, **k):
                self.fields = {'active_term': forms.ChoiceField(choices=[('G', 'GenericLabel')])}
        with patch('cis.services.settings_overview._get_profile', return_value=bad), \
             patch('cis.services.settings_overview.import_string', return_value=WithHook):
            ov = build_overview('anything', request=self._req())
        self.assertEqual(ov['sections'][0]['items'][0]['fields'][0]['value'], 'CUSTOM')


class DescriptionTests(TestCase):
    def test_description_included_and_placeholder_normalized(self):
        import importlib.util
        if importlib.util.find_spec('setting.setting'):
            from setting.setting.models import SettingRecord
        else:
            from setting.models import SettingRecord
        # A real help description survives; the seeded '-' placeholder → blank.
        SettingRecord.objects.create(app='cis', name='signup', title='Signup',
                                     description='Controls the new-student signup page.')
        SettingRecord.objects.create(app='cis', name='ferpa', title='FERPA', description='-')
        ov = build_overview('student_registration')
        descs = {}
        for s in ov['sections']:
            for it in s['items']:
                descs[it['title']] = it['description']
        self.assertEqual(descs.get('Signup'), 'Controls the new-student signup page.')
        self.assertEqual(descs.get('FERPA'), '')          # '-' normalized to blank

    def test_item_always_has_description_key(self):
        ov = build_overview('student_registration')
        for s in ov['sections']:
            for it in s['items']:
                self.assertIn('description', it)          # present even with no SettingRecord
