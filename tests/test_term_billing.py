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

    def _sa(self, student, term):
        from cis.models.student import StudentAgreement
        return StudentAgreement.objects.create(
            student=student, term=term, student_signature='S')

    def test_has_signed_for_billing_term_accepts_sub_term_rows(self):
        from cis.models.student import StudentAgreement
        student = self.registrations['Fall Semester'].student
        self.assertFalse(StudentAgreement.has_signed_for_billing_term(student, self.P))
        self._sa(student, self.A)
        self._sa(student, self.B)
        self.assertTrue(StudentAgreement.has_signed_for_billing_term(student, self.P))

    def test_has_signed_for_billing_term_own_row_and_other_terms(self):
        from cis.models.student import StudentAgreement
        student = self.registrations['Fall Semester'].student
        self._sa(student, self.spring)
        self.assertFalse(StudentAgreement.has_signed_for_billing_term(student, self.P))
        self.C.bills_with_parent = False
        self.C.save()
        self.assertFalse(StudentAgreement.has_signed_for_billing_term(student, self.C))
        self._sa(student, self.C)
        self.assertTrue(StudentAgreement.has_signed_for_billing_term(student, self.C))
        self.assertTrue(StudentAgreement.has_signed_for_billing_term(student, self.P))
        other = self.registrations['Spring'].student
        self.assertFalse(StudentAgreement.has_signed_for_billing_term(other, self.P))

    def test_has_signed_for_billing_term_accepts_parent_row(self):
        # Tenants that list [P] as the registration terms save SAs only on P;
        # a separately billed sub-term C must accept that row.
        from cis.models.student import StudentAgreement
        self.C.bills_with_parent = False
        self.C.save()
        student = self.registrations['Fall Semester'].student
        self._sa(student, self.P)
        self.assertTrue(StudentAgreement.has_signed_for_billing_term(student, self.C))
        self.assertTrue(StudentAgreement.has_signed_for_billing_term(student, self.P))
        self.assertFalse(StudentAgreement.has_signed_for_billing_term(student, self.spring))

    def _statement_qr_url(self, eligible):
        from unittest import mock
        from django.test import RequestFactory
        student = self.registrations['Fall Semester'].student
        student.current_student_balance = 100
        captured = []
        request = RequestFactory().get('/', {'mode': 'page'})
        with mock.patch('cis.utils.active_term', return_value=self.A), \
                mock.patch('cis.utils.qr_code', side_effect=lambda u: captured.append(u)), \
                mock.patch.object(type(student), 'is_eligible_to_pay',
                                  return_value=(eligible, [])), \
                mock.patch.object(type(student), 'has_signed_parent_consent_for_term',
                                  return_value=False):
            student.generate_account_statement(request)
        return captured[0]

    def test_account_statement_payment_qr_uses_billing_term(self):
        url = self._statement_qr_url(eligible=True)
        self.assertIn(str(self.P.id), url)
        self.assertNotIn(str(self.A.id), url)

    def test_account_statement_consent_qr_uses_billing_term(self):
        url = self._statement_qr_url(eligible=False)
        self.assertIn(str(self.P.id), url)
        self.assertNotIn(str(self.A.id), url)
