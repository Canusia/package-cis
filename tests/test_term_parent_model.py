from django.test import TestCase

from cis.models.term import AcademicYear, Term


class TermParentModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ay = AcademicYear.objects.create(name='2024-2025')
        cls.year = Term.objects.create(academic_year=cls.ay, code='2024', label='Year')
        cls.term = Term.objects.create(academic_year=cls.ay, code='24FA', label='Fall')
        cls.sub = Term.objects.create(academic_year=cls.ay, code='24FA1', label='Fall A')

    def test_would_create_cycle_rejects_self(self):
        self.assertTrue(self.term.would_create_cycle(self.term))

    def test_would_create_cycle_rejects_direct_descendant(self):
        # sub -> term (sub's parent is term); making term's parent = sub is a cycle
        self.sub.parent = self.term
        self.sub.save()
        self.assertTrue(self.term.would_create_cycle(self.sub))

    def test_would_create_cycle_rejects_transitive_descendant(self):
        # year <- term <- sub ; making year's parent = sub is a cycle
        self.term.parent = self.year
        self.term.save()
        self.sub.parent = self.term
        self.sub.save()
        self.assertTrue(self.year.would_create_cycle(self.sub))

    def test_would_create_cycle_allows_unrelated(self):
        self.assertFalse(self.term.would_create_cycle(self.year))

    def test_would_create_cycle_allows_none(self):
        self.assertFalse(self.term.would_create_cycle(None))

    def test_parent_set_null_on_delete(self):
        self.sub.parent = self.term
        self.sub.save()
        self.term.delete()
        self.sub.refresh_from_db()
        self.assertIsNone(self.sub.parent_id)
