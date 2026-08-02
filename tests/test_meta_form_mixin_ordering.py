"""apply_field_weights / _load_field_labels_from_db live on MetaFormMixin, so
both form paths (legacy profile and spec-driven application) order and relabel
fields from the same setting."""
from django import forms
from django.test import TestCase

from cis.forms.utils import MetaFormMixin
from cis.models.settings import Setting
from cis.settings.student_profile import student_profile


class _TinyForm(MetaFormMixin, forms.Form):
    alpha = forms.CharField(required=False)
    beta = forms.CharField(required=False)
    gamma = forms.CharField(required=False)


class MetaFormMixinOrderingTest(TestCase):

    def _write_setting(self, value):
        Setting.objects.update_or_create(
            key=student_profile.key, defaults={'value': value})

    def test_mixin_exposes_both_helpers(self):
        self.assertTrue(hasattr(MetaFormMixin, 'apply_field_weights'))
        self.assertTrue(hasattr(MetaFormMixin, '_load_field_labels_from_db'))

    def test_weights_reorder_fields(self):
        self._write_setting({'field_weights': {'gamma': 5, 'alpha': 30}})
        form = _TinyForm()
        form.apply_field_weights()
        # beta is unweighted, so it rides along right after alpha (its
        # predecessor in declaration order) at alpha's weight + epsilon.
        self.assertEqual(list(form.fields), ['gamma', 'alpha', 'beta'])

    def test_no_weights_leaves_order_untouched(self):
        self._write_setting({'field_weights': {}})
        form = _TinyForm()
        form.apply_field_weights()
        self.assertEqual(list(form.fields), ['alpha', 'beta', 'gamma'])

    def test_field_messages_override_label_and_help_text(self):
        self._write_setting({'field_messages': {
            'beta': {'label': 'Renamed Beta', 'help_text': 'Some <b>help</b>'}}})
        form = _TinyForm()
        form._load_field_labels_from_db()
        self.assertEqual(str(form.fields['beta'].label), 'Renamed Beta')
        self.assertEqual(str(form.fields['beta'].help_text), 'Some <b>help</b>')
