"""Assign StudentFerpa.campus and move freshness onto the row (#65).

Single-campus: every row gets the deployment campus (first prefixed campus by
name, the rule of campus_context.deployment_campus() and 0097), and
completed_for/completed_on come from the student's meta.

Multi-campus: a row whose permissions_granted['college_name'] matches exactly
one campus name gets that campus (and the meta freshness); anything else stays
null, so the student signs again on each campus. student.meta is not modified.
"""
import datetime
import logging

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)


def _date(value):
    try:
        return datetime.datetime.strptime(str(value or ''), '%m/%d/%Y').date()
    except ValueError:
        return None


def forward(apps, schema_editor):
    Campus = apps.get_model('cis', 'Campus')
    StudentFerpa = apps.get_model('cis', 'StudentFerpa')

    multi = getattr(settings, 'MULTI_CAMPUS', False)
    deployment = None
    by_name = {}
    if multi:
        for campus in Campus.objects.all():
            by_name.setdefault(campus.name, []).append(campus)
    else:
        deployment = Campus.objects.filter(
            code__startswith=settings.CAMPUS_CODE_PREFIX).order_by('name').first()
        if deployment is None:
            logger.warning('No campus with code prefix %r; FERPA records left '
                           'unassigned.', settings.CAMPUS_CODE_PREFIX)

    for row in StudentFerpa.objects.filter(campus__isnull=True).select_related('student'):
        if multi:
            name = (row.permissions_granted or {}).get('college_name')
            matches = by_name.get(name, [])
            campus = matches[0] if len(matches) == 1 else None
        else:
            campus = deployment
        if campus is None:
            continue
        meta = row.student.meta if isinstance(row.student.meta, dict) else {}
        StudentFerpa.objects.filter(pk=row.pk).update(
            campus=campus,
            completed_for=list(meta.get('ferpa_completed_for') or []),
            completed_on=_date(meta.get('ferpa_completed_on')))


def backward(apps, schema_editor):
    StudentFerpa = apps.get_model('cis', 'StudentFerpa')
    for row in StudentFerpa.objects.exclude(campus__isnull=True).select_related('student'):
        student = row.student
        meta = dict(student.meta) if isinstance(student.meta, dict) else {}
        meta['ferpa_completed_for'] = list(row.completed_for or [])
        if row.completed_on:
            meta['ferpa_completed_on'] = row.completed_on.strftime('%m/%d/%Y')
        student.meta = meta
        student.save(update_fields=['meta'])
    StudentFerpa.objects.update(campus=None, completed_for=[], completed_on=None)


class Migration(migrations.Migration):

    dependencies = [('cis', '0104_studentferpa_campus_fk')]

    operations = [migrations.RunPython(forward, backward)]
