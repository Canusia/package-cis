"""A saved ClassSection always ends up with a registration term.

`ClassSection.registration_term` is nullable and many sections only ever set
`term`. The charge signal in `student_transactions` writes
`term=instance.class_section.registration_term` into
`StudentTransaction.term`, which is NOT NULL, so applying for a class on such a
section failed with

    null value in column "term_id" of relation "student_transactions_studenttransaction"

surfaced to the student as the misleading "You have already added it". Seen on
SCCC with ~1600 sections in that state. See ewu#53.

The fix is a cis-side safety default: a blank registration term is derived on
save. Registration happens against the *parent* term when the academic term has
one -- a child term (a session or sub-term) registers under the term that owns
it -- and against the term itself otherwise. The charge writer stays where it
is.
"""
from django.test import TestCase

from cis.models.course import Cohort, Course
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.models.term import AcademicYear, Term


class RegistrationTermDefaultTests(TestCase):
    def setUp(self):
        ay = AcademicYear.objects.create(name='AY RT')
        self.term = Term.objects.create(
            academic_year=ay, code='F30', label='Fall 30')
        self.other_term = Term.objects.create(
            academic_year=ay, code='S31', label='Spring 31')
        self.parent_term = Term.objects.create(
            academic_year=ay, code='P30', label='Parent 30')
        self.child_term = Term.objects.create(
            academic_year=ay, code='C30', label='Child 30',
            parent=self.parent_term)
        self.hs = HighSchool.objects.create(name='HS RT')
        cohort = Cohort.objects.create(name='Cohort RT', designator='RT')
        self.course = Course.objects.create(
            catalog_number='101', title='Intro', name='COURSE RT',
            cohort=cohort, credit_hours=3)

    def _section(self, **kwargs):
        return ClassSection.objects.create(
            course=self.course, highschool=self.hs,
            class_number=kwargs.pop('class_number', 'CN-RT'),
            section_number='01', **kwargs)

    def test_blank_registration_term_falls_back_to_the_term(self):
        """No parent term: the section registers under its own term."""
        section = self._section(term=self.term)

        section.refresh_from_db()
        self.assertEqual(section.registration_term_id, self.term.id)

    def test_blank_registration_term_prefers_the_parent_term(self):
        """A child term (a session or sub-term) registers under the term that
        owns it, not under itself."""
        section = self._section(term=self.child_term, class_number='CN-RT4')

        section.refresh_from_db()
        self.assertEqual(section.registration_term_id, self.parent_term.id)

    def test_an_explicit_registration_term_is_left_alone(self):
        """The fallback must not overwrite a section that deliberately
        registers against a different term -- that is the whole reason the two
        fields exist separately."""
        section = self._section(
            term=self.term, registration_term=self.other_term,
            class_number='CN-RT2')

        section.refresh_from_db()
        self.assertEqual(section.registration_term_id, self.other_term.id)

    def test_clearing_the_registration_term_later_restores_the_fallback(self):
        """An edit that blanks the field must not reopen the hole."""
        section = self._section(
            term=self.term, registration_term=self.other_term,
            class_number='CN-RT3')

        section.registration_term = None
        section.save()

        section.refresh_from_db()
        self.assertEqual(section.registration_term_id, self.term.id)

    def test_clearing_on_a_child_term_restores_the_parent(self):
        section = self._section(
            term=self.child_term, registration_term=self.other_term,
            class_number='CN-RT5')

        section.registration_term = None
        section.save()

        section.refresh_from_db()
        self.assertEqual(section.registration_term_id, self.parent_term.id)

    def test_only_the_immediate_parent_is_used(self):
        """One level, not the root of the chain -- a grandchild registers under
        its own parent, which may itself be a child."""
        grandchild = Term.objects.create(
            academic_year=self.term.academic_year, code='G30',
            label='Grandchild 30', parent=self.child_term)

        section = self._section(term=grandchild, class_number='CN-RT6')

        section.refresh_from_db()
        self.assertEqual(section.registration_term_id, self.child_term.id)
