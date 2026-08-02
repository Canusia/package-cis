from django.test import TestCase

from cis.models.term import AcademicYear, Term
from cis.serializers.term import TermSerializer


class TermParentSerializerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ay = AcademicYear.objects.create(name='2024-2025')
        cls.parent = Term.objects.create(academic_year=cls.ay, code='24FA', label='Fall')
        cls.child = Term.objects.create(
            academic_year=cls.ay, code='24FA1', label='Fall A', parent=cls.parent)

    def test_parent_serialized_as_id_and_label(self):
        data = TermSerializer(self.child).data
        self.assertEqual(str(data['parent']['id']), str(self.parent.id))
        self.assertEqual(data['parent']['label'], 'Fall')

    def test_null_parent_serialized_as_none(self):
        data = TermSerializer(self.parent).data
        self.assertIsNone(data['parent'])
