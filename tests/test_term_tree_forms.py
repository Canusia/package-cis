"""Assigning/settings term pickers render the tree; the parent picker can't make cycles."""
from django.test import TestCase

from cis.forms.term import BulkAssignParentForm, TermForm
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin


def choice_ids(field):
    return [str(value) for value, _ in field.choices if value != '']


class TermFormTreeTests(TermTreeFixtureMixin, TestCase):
    def test_parent_picker_excludes_self_and_descendants(self):
        form = TermForm(instance=self.quarter)
        ids = choice_ids(form.fields['parent'])
        for pk in (self.quarter.pk, self.semester.pk, self.trimester.pk):
            self.assertNotIn(str(pk), ids)
        self.assertIn(str(self.spring.pk), ids)

    def test_parent_picker_is_tree_ordered(self):
        form = TermForm(instance=self.spring)
        ids = choice_ids(form.fields['parent'])
        self.assertEqual(ids.index(str(self.quarter.pk)) + 1, ids.index(str(self.semester.pk)))

    def test_bulk_assign_parent_tree_ordered_and_valid(self):
        form = BulkAssignParentForm(
            ids=[str(self.spring.pk)], data={'parent': str(self.semester.pk)})
        ids = choice_ids(form.fields['parent'])
        self.assertLess(ids.index(str(self.quarter.pk)), ids.index(str(self.semester.pk)))
        self.assertTrue(form.is_valid(), form.errors)


class SettingsTreeTests(TermTreeFixtureMixin, TestCase):
    def test_registration_settings_choices_tree_ordered(self):
        from cis.settings.registrations import RegistrationForm
        form = RegistrationForm()
        ids = choice_ids(form.fields['registration_terms'])
        self.assertEqual(ids.index(str(self.quarter.pk)) + 1, ids.index(str(self.semester.pk)))
        labels = dict((str(v), str(l)) for v, l in form.fields['active_term'].choices)
        self.assertTrue(labels[str(self.semester.pk)].startswith('\xa0\xa0\xa0'))
