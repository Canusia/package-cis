"""Link every high school to the deployment's campus on single-campus tenants.

Single-campus (MULTI_CAMPUS off): the deployment campus is the first prefixed
campus by name -- the same rule as cis.campus_context.deployment_campus(),
so the backfill and the runtime agree. With no prefixed campus nothing is
linked. Multi-campus deployments are left unlinked; their schools are linked
with assign_highschool_campus.

Each linked school's own status is then written as the derived value (Active
if its link is Active, else Inactive). Historical models fire no signals, so
the migration does it itself.
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

    campus = Campus.objects.filter(
        code__startswith=settings.CAMPUS_CODE_PREFIX).order_by('name').first()
    if campus is None:
        logger.warning(
            'No campus with code prefix %r; high schools left unlinked.',
            settings.CAMPUS_CODE_PREFIX)
        return

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
        norm = (hs.status or '').strip().lower()
        if norm not in ('active', 'inactive'):
            logger.warning(
                'High school %s: non-standard status %r linked as Inactive.',
                hs.pk, hs.status)
        HighSchoolCampus.objects.create(
            highschool=hs, campus=campus, building_code=code,
            status='Active' if norm == 'active' else 'Inactive')

    # Derived status, for every linked school (only this campus's links exist
    # on a single-campus deployment, but derive from all to be exact).
    linked = HighSchoolCampus.objects.values_list('highschool_id', flat=True)
    active = HighSchoolCampus.objects.filter(status='Active').values_list(
        'highschool_id', flat=True)
    HighSchool.objects.filter(pk__in=active).update(status='Active')
    HighSchool.objects.filter(pk__in=linked).exclude(pk__in=active).update(
        status='Inactive')


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0096_highschool_campus'),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
