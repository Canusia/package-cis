"""Student balances go through cis.services.student_balances (#88, #114
item 6): the package default is unchanged, and a tenant can replace any of
debits / credits / student_balance / school_balance / balances."""
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models.student import Student
from cis.models.term import AcademicYear, Term

User = get_user_model()


class StudentBalancesSeamTests(TestCase):
    def setUp(self):
        from student_transactions.models import StudentTransaction

        Group.objects.get_or_create(name='student')
        sfx = uuid.uuid4().hex[:8]
        user = User.objects.create_user(
            username=f'bal_{sfx}', email=f'bal_{sfx}@x.com', password='x')
        self.student = Student.objects.create(user=user, account_verified=True)
        year = AcademicYear.objects.create(name=f'bal-{sfx}')
        term = Term.objects.create(academic_year=year, code=f'B{sfx}', label='Fall')
        for t_type, label, amount in (
                ('debit', 'class_charge', 300), ('credit', 'payment', 100),
                ('debit', 'school_charge', 50), ('credit', 'school_pay', 20)):
            StudentTransaction.objects.create(
                student=self.student, term=term, t_type=t_type, label=label,
                amount=amount)

    def test_default_balances_are_unchanged(self):
        self.assertEqual(self.student.student_balance(), 200.0)
        self.assertEqual(self.student.school_balance(), 30.0)
        self.assertEqual(self.student.debits().count(), 1)
        self.assertEqual(self.student.debits(None, 'school_charge').count(), 1)
        self.assertEqual(self.student.credits(label='school_pay').count(), 1)

    def test_balances_lists_every_payer(self):
        self.assertEqual(self.student.balances(), {'student': 200.0, 'school': 30.0})

    def test_state_balance_field_defaults_to_zero(self):
        self.assertEqual(self.student.current_state_balance, 0.0)

    def test_tenant_override_replaces_one_function(self):
        def tenant_student_balance(student, term=None, **opts):
            return 1.5

        def override(module, attr):
            self.assertEqual(module, 'student_balances')
            return tenant_student_balance if attr == 'student_balance' else None

        with mock.patch('cis.services.student_balances.get_tenant_override', override):
            self.assertEqual(self.student.student_balance(), 1.5)
            self.assertEqual(self.student.school_balance(), 30.0)
            self.assertEqual(self.student.balances(), {'student': 1.5, 'school': 30.0})

    def test_tenant_keywords_pass_through(self):
        seen = {}

        def tenant_debits(student, term=None, **filters):
            seen.update(filters)
            return []

        with mock.patch('cis.services.student_balances.get_tenant_override',
                        lambda m, a: tenant_debits if a == 'debits' else None):
            self.student.debits(payer='state')
        self.assertEqual(seen, {'payer': 'state'})
