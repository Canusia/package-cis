"""Link every high school to the deployment's campus on single-campus tenants.

Multi-campus deployments (MULTI_CAMPUS on, or not exactly one prefixed campus)
are left unlinked; their schools are linked with assign_highschool_campus.
"""
import logging

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)


def forward(apps, schema_editor):
    if getattr(settings, 'MULTI_CAMPUS', False):
        return

    Campus = apps.get_model('cis', 'Campus')
    HighSchool = apps.get_model('cis', 'HighSchool')
    HighSchoolCampus = apps.get_model('cis', 'HighSchoolCampus')

    campuses = list(Campus.objects.filter(
        code__startswith=settings.CAMPUS_CODE_PREFIX)[:2])
    if len(campuses) != 1:
        return
    campus = campuses[0]

    used = set(HighSchoolCampus.objects.filter(campus=campus).exclude(
        building_code='').values_list('building_code', flat=True))
    existing = set(HighSchoolCampus.objects.filter(
        campus=campus).values_list('highschool_id', flat=True))

    for hs in HighSchool.objects.order_by('name', 'pk'):
        if hs.pk in existing:
            continue
        code = (hs.sau or '').strip()
        if code in ('', '-'):
            code = ''
        elif len(code) > 20:
            logger.warning(
                'High school %s (%s): sau %r is longer than 20 characters; '
                'building code left empty.', hs.name, hs.pk, code)
            code = ''
        elif code in used:
            logger.warning(
                'High school %s (%s): building code %r already held on '
                'campus %s; left empty.', hs.name, hs.pk, code, campus.code)
            code = ''
        else:
            used.add(code)
        if hs.status not in ('Active', 'Inactive'):
            logger.warning(
                'High school %s: non-standard status %r linked as Inactive.',
                hs.pk, hs.status)
        HighSchoolCampus.objects.create(
            highschool=hs, campus=campus, building_code=code,
            status='Active' if hs.status == 'Active' else 'Inactive')


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0096_highschool_campus'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
