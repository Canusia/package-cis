from django.test import TestCase

from cis.forms.course import CourseForm
from cis.models.course import Campus


class CourseFormFieldExposureTests(TestCase):
    """CourseForm (course add + edit) should expose `campus` as an editable
    field and should NOT expose the raw `meta` JSON field — the meaningful
    meta values are surfaced via the dedicated `available_for_si` /
    `available_for_new_schools` choice fields and persisted by the view."""

    def test_campus_is_an_editable_field(self):
        self.assertIn('campus', CourseForm().fields)

    def test_meta_is_not_a_field(self):
        self.assertNotIn('meta', CourseForm().fields)

    def test_campus_choices_ordered_by_name(self):
        Campus.objects.create(name='Zed Campus', code='ZED')
        Campus.objects.create(name='Alpha Campus', code='ALP')
        qs = CourseForm().fields['campus'].queryset
        names = list(qs.values_list('name', flat=True))
        self.assertEqual(names, sorted(names))
