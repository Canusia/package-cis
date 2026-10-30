from django.test import TestCase

from cis.forms.term import TermForm
from cis.models.section import ClassSection, StudentRegistration
from cis.models.term import Term, billed_to_q
from cis.tests.term_tree_fixtures import TermTreeFixtureMixin, make_registration, sfx


class TermBillingTests(TermTreeFixtureMixin, TestCase):
    """quarter (P) -> semester (A), trimester (B); C is added here."""

    def setUp(self):
        super().setUp()
        self.P, self.A, self.B = self.quarter, self.semester, self.trimester
        self.C = Term.objects.create(
            academic_year=self.ay, code='270', label='Fall Summer', parent=self.P)

    def _section(self, term):
        return ClassSection.objects.create(
            class_number=f'CN{sfx()}', section_number='01', term=term,
            registration_term=term, course=self.course, highschool=self.hs,
            status='A')

    def test_sub_term_bills_with_parent_by_default(self):
        self.assertEqual(self.A.billing_term, self.P)

    def test_sub_term_billed_separately(self):
        self.C.bills_with_parent = False
        self.C.save()
        self.assertEqual(self.C.billing_term, self.C)

    def test_term_without_parent_bills_itself(self):
        self.assertEqual(self.P.billing_term, self.P)
        self.assertEqual(self.spring.billing_term, self.spring)

    def test_billing_terms_under_parent(self):
        self.C.bills_with_parent = False
        self.C.save()
        self.assertEqual(self.P.billing_terms_under(), [self.P, self.C])

    def test_section_billing_term(self):
        self.assertEqual(self._section(self.A).billing_term, self.P)

    def test_billed_to_q(self):
        self.C.bills_with_parent = False
        self.C.save()
        sp, sa, sc = self._section(self.P), self._section(self.A), self._section(self.C)
        qs = ClassSection.objects.filter
        self.assertEqual(set(qs(billed_to_q(self.P))), {sp, sa} | {
            s for s in (self.sections['Fall Trimester'], self.sections['Fall Semester'])})
        self.assertEqual(set(qs(billed_to_q(self.C))), {sc})
        ra, rc = make_registration(sa), make_registration(sc)
        rp = StudentRegistration.objects.filter(billed_to_q(self.P, 'class_section__'))
        self.assertIn(ra, rp)
        self.assertNotIn(rc, rp)
        rcq = StudentRegistration.objects.filter(billed_to_q(self.C, 'class_section__'))
        self.assertEqual(set(rcq), {rc})

    def _post(self, flag):
        data = {
            'academic_year': str(self.ay.pk), 'parent': str(self.P.pk),
            'code': self.A.code, 'label': self.A.label,
        }
        if flag:
            data['bills_with_parent'] = 'on'
        return TermForm(data, instance=self.A)

    def test_term_form_refuses_flip_with_charges(self):
        form = self._post(False)
        self.assertTrue(form.is_valid(), form.errors)

        from student_transactions.models import StudentTransaction
        reg = self.registrations['Fall Semester']
        StudentTransaction.objects.create(
            student=reg.student, t_type='debit', label='class_charge',
            amount=10, term=self.P, meta={'registration': str(reg.id)})

        form = self._post(False)
        self.assertFalse(form.is_valid())
        self.assertIn('bills_with_parent', form.errors)
        self.assertTrue(self._post(True).is_valid())
