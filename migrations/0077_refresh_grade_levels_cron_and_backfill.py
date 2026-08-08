"""Schedule the grade-level refresh, and correct the rows already wrong.

Two things, deliberately together: the cron alone would leave every existing
student wrong until the next rollover, which is up to a year away.

The backfill re-derives from each student's own graduation year/date. It only
ever writes a real grade — the derivation's sentinels (GRAD, '--', None) are
not valid choices, and a student who hits one keeps whatever they had rather
than being blanked. So a graduated student stays SR here instead of losing
their grade level, which is the conservative direction: a blank grade_level
makes a registration invisible to high school admins.

Reversible in the sense that matters — the cron row is removed on reverse. The
backfill is not un-done, because the values it replaces were wrong; restoring
them would mean recreating the bug.
"""
from django.db import migrations

COMMAND = 'refresh_student_grade_levels'


def _cron_expression():
    """1st of the rollover month, when the academic year turns over."""
    from cis.academic_calendar import GRADE_LEVEL_ROLLOVER_MONTH
    return f'0 0 1 {GRADE_LEVEL_ROLLOVER_MONTH} *'


def add_cron(apps, schema_editor):
    CronTab = apps.get_model('cis', 'CronTab')
    CronTab.objects.update_or_create(
        command=COMMAND, defaults={'cron': _cron_expression()})


def remove_cron(apps, schema_editor):
    CronTab = apps.get_model('cis', 'CronTab')
    CronTab.objects.filter(command=COMMAND).delete()


def backfill_grade_levels(apps, schema_editor):
    # Imported rather than taken from the historical model: this is pure
    # date arithmetic with no model state, so it cannot drift with the schema.
    from cis.academic_calendar import grade_level_from_graduation

    Student = apps.get_model('cis', 'Student')
    valid = {'FR', 'SO', 'JR', 'SR'}

    updates = []
    queryset = Student.objects.exclude(
        graduation_date__isnull=True, graduation_year__isnull=True)

    for student in queryset.only(
            'id', 'grade_level', 'graduation_date', 'graduation_year').iterator():
        computed = grade_level_from_graduation(
            graduation_year=student.graduation_year,
            graduation_date=student.graduation_date)
        if computed in valid and computed != (student.grade_level or ''):
            student.grade_level = computed
            updates.append(student)

    if updates:
        Student.objects.bulk_update(updates, ['grade_level'], batch_size=500)


def noop(apps, schema_editor):
    """Reverse of the backfill: the previous values were wrong, so there is
    nothing worth restoring."""


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0076_registration_term_prefers_parent_term'),
    ]

    operations = [
        migrations.RunPython(add_cron, remove_cron),
        migrations.RunPython(backfill_grade_levels, noop),
    ]
