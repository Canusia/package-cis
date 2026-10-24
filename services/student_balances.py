"""Student ledger balances (#88, #114 item 6).

The package default partitions the StudentTransaction ledger by ``label``:
class charges and payments are the student's, ``school_charge`` /
``school_pay`` the school's. A tenant that partitions it another way (nnu by
``payer``, with a state-funds payer) ships ``services/student_balances.py`` in
its TENANT_SERVICES_APP defining any of ``debits``, ``credits``,
``student_balance``, ``school_balance`` and ``balances``, with the same
``(student, term=None, ...)`` shape; the ones it leaves out fall back to these.
The ``Student`` methods of the same names delegate here, so the package's call
sites stay unchanged.
"""
from django.db import models

from cis.services.tenant_services import get_tenant_override


# The defaults call each other directly, not through resolve(): a tenant that
# overrides debits() with its own keywords (nnu: payer=) overrides the
# balances built on it too.
def resolve(name):
    """The tenant's override of balance function ``name``, else the default."""
    return get_tenant_override('student_balances', name) or globals()[name]


def debits(student, term=None, label='class_charge', sequence_only=False):
    from student_transactions.models import StudentTransaction

    records = StudentTransaction.objects.filter(
        student=student,
        t_type='debit'
    )

    if sequence_only & False:
        from cis.models.section import StudentRegistration
        sequence_sections = StudentRegistration.objects.filter(
            student=student,
            class_section__is_sequence='1'
        )

        if term:
            sequence_sections = sequence_sections.filter(
                class_section__term=term
            )

        sequence_section_ids = []
        for seq_section in sequence_sections:
            sequence_section_ids.append(str(seq_section.id))

        records = records.filter(
            meta__registration__in=sequence_section_ids
        )

    if label != 'school_charge':
        records = records.exclude(label='school_charge')
    else:
        records = records.filter(label=label)

    if term:
        records = records.filter(term=term)

    records = records.order_by('-created_on')
    return records


def credits(student, term=None, label=None):
    from student_transactions.models import StudentTransaction

    records = StudentTransaction.objects.filter(
        student=student,
        t_type='credit'
    )

    if label:
        if label == 'school_pay':
            label = [
                'school_pay',
                '2'
            ]
        records = records.filter(label__in=label)
    else:
        records = records.exclude(
            label__in=['school_pay', '2']
        )

    if term:
        records = records.filter(term=term)

    records = records.order_by('-created_on')
    return records


def student_balance(student, term=None, sequence=False):

    charges = debits(student, term, 'class_charge', sequence_only=sequence)

    total_charges = charges.aggregate(models.Sum('amount'))

    if total_charges['amount__sum'] == None:
        total_charges = 0
    else:
        total_charges = total_charges['amount__sum']

    payments = credits(student, term, label=None)
    # charges = charges.exclude(label='2')

    total_payments = payments.aggregate(models.Sum('amount'))

    if total_payments['amount__sum'] == None:
        total_payments = 0
    else:
        total_payments = total_payments['amount__sum']

    return float(total_charges) - float(total_payments)


def school_balance(student, term=None):

    charges = debits(student, term, 'school_charge')
    total_charges = charges.aggregate(models.Sum('amount'))

    if total_charges['amount__sum'] == None:
        total_charges = 0
    else:
        total_charges = total_charges['amount__sum']

    payments = credits(student, term, label='school_pay')
    total_payments = payments.aggregate(models.Sum('amount'))

    if total_payments['amount__sum'] == None:
        total_payments = 0
    else:
        total_payments = total_payments['amount__sum']

    return float(total_charges) - float(total_payments)


def balances(student, term=None):
    """Every payer's balance, e.g. {'student': 12.0, 'school': 0.0}. Pages that
    show all of them read this, so a tenant can add a payer (nnu: 'state')
    without touching package templates."""
    return {
        'student': resolve('student_balance')(student, term),
        'school': resolve('school_balance')(student, term),
    }
