"""DualListSelectMultiple: Django-admin-style Available / Chosen lists that
post exactly what a plain SelectMultiple posts."""
from django import forms
from django.test import SimpleTestCase

from cis.forms.widgets import DualListSelectMultiple

CHOICES = [('1', 'Can bulk enroll'), ('2', 'Can submit grades'), ('3', 'Can verify class rosters')]


class _Form(forms.Form):
    grant = forms.MultipleChoiceField(
        choices=CHOICES, required=False, widget=DualListSelectMultiple)


class DualListWidgetTests(SimpleTestCase):
    def _html(self, **kwargs):
        return str(_Form(**kwargs)['grant'])

    def test_renders_the_real_select_hidden_with_all_options(self):
        html = self._html(initial={'grant': ['2']})
        self.assertIn('data-duallist', html)
        self.assertRegex(html, r'<select[^>]*name="grant"[^>]*multiple')
        self.assertEqual(html.count('name="grant"'), 1)
        for value, label in CHOICES:
            self.assertIn(label, html)
        self.assertRegex(html, r'<option value="2"[^>]*selected')
        self.assertNotRegex(html, r'<option value="1"[^>]*selected')

    def test_renders_available_and_chosen_lists_with_controls(self):
        html = self._html()
        self.assertIn('Available', html)
        self.assertIn('Chosen', html)
        for control in ('data-dl-add', 'data-dl-remove', 'data-dl-add-all',
                        'data-dl-remove-all', 'data-dl-filter'):
            self.assertIn(control, html)

    def test_posts_like_a_plain_select_multiple(self):
        form = _Form(data={'grant': ['1', '3']})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['grant'], ['1', '3'])

    def test_disabled_renders_read_only_without_controls(self):
        form = _Form(initial={'grant': ['2']})
        form.fields['grant'].disabled = True
        html = str(form['grant'])
        self.assertIn('Can submit grades', html)
        self.assertNotIn('data-dl-add', html)
        self.assertNotIn('data-dl-filter', html)

    def test_two_instances_get_distinct_ids(self):
        class TwoForm(forms.Form):
            grant = forms.MultipleChoiceField(choices=CHOICES, required=False,
                                              widget=DualListSelectMultiple)
            revoke = forms.MultipleChoiceField(choices=CHOICES, required=False,
                                               widget=DualListSelectMultiple)
        html = str(TwoForm()['grant']) + str(TwoForm()['revoke'])
        self.assertIn('id="id_grant_duallist"', html)
        self.assertIn('id="id_revoke_duallist"', html)
