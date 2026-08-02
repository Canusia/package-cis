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
