from django.test import TestCase

from cis.forms.term import TermForm
from cis.models.term import AcademicYear, Term


class TermParentFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ay = AcademicYear.objects.create(name='2024-2025')
        cls.term = Term.objects.create(academic_year=cls.ay, code='24FA', label='Fall')
        cls.sub = Term.objects.create(academic_year=cls.ay, code='24FA1', label='Fall A')

    def _data(self, **over):
        data = {'academic_year': str(self.ay.id), 'code': '24FA', 'label': 'Fall'}
        data.update(over)
        return data

    def test_edit_queryset_excludes_self(self):
        form = TermForm(instance=self.term)
        self.assertNotIn(self.term, form.fields['parent'].queryset)

    def test_rejects_self_parent(self):
        form = TermForm(self._data(parent=str(self.term.id)), instance=self.term)
        self.assertFalse(form.is_valid())
        self.assertIn('parent', form.errors)

    def test_rejects_cycle(self):
        self.sub.parent = self.term
        self.sub.save()
        form = TermForm(self._data(parent=str(self.sub.id)), instance=self.term)
        self.assertFalse(form.is_valid())
        self.assertIn('parent', form.errors)

    def test_allows_valid_parent(self):
        form = TermForm(self._data(parent=str(self.sub.id)), instance=self.term)
        self.assertTrue(form.is_valid(), form.errors.as_json())
