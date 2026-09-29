"""Make CustomUser.process_campuses the only source of staff campuses (#59).

Until now campus['process_campus'] (JSON) was authoritative and the M2M a
copy refreshed on save; QuerySet.update() could leave them apart. So, for
every user: first bring the M2M in line with the JSON (the JSON is still
right at this point), then rewrite the JSON from the M2M -- after which it
is only a mirror. Ids of campuses that no longer exist drop out of both.
"""
import uuid

from django.db import migrations


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def resync(apps, schema_editor):
    User = apps.get_model('cis', 'CustomUser')
    Campus = apps.get_model('cis', 'Campus')
    through = User.process_campuses.through
    names = dict(Campus.objects.values_list('id', 'name'))

    users = User.objects.filter(campus__has_key='process_campus')
    for user_id, perms in users.values_list('id', 'campus').iterator():
        wanted = []
        for value in (perms or {}).get('process_campus') or []:
            campus_id = _uuid(value)
            if campus_id in names and campus_id not in wanted:
                wanted.append(campus_id)
        through.objects.filter(customuser_id=user_id).exclude(campus_id__in=wanted).delete()
        have = set(through.objects.filter(customuser_id=user_id).values_list('campus_id', flat=True))
        through.objects.bulk_create(
            [through(customuser_id=user_id, campus_id=c) for c in wanted if c not in have])
        perms = dict(perms or {})
        perms['process_campus'] = [str(c) for c in sorted(wanted, key=lambda c: names[c])]
        User.objects.filter(pk=user_id).update(campus=perms)

    # Users with M2M rows but no JSON key (none expected) get a mirror too.
    orphan_ids = set(through.objects.values_list('customuser_id', flat=True)) - set(
        users.values_list('id', flat=True))
    for user_id, perms in User.objects.filter(id__in=orphan_ids).values_list('id', 'campus'):
        ids = through.objects.filter(customuser_id=user_id).values_list('campus_id', flat=True)
        perms = dict(perms or {})
        perms['process_campus'] = [str(c) for c in sorted(ids, key=lambda c: names[c])]
        User.objects.filter(pk=user_id).update(campus=perms)


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0093_user_process_campuses'),
    ]

    operations = [
        migrations.RunPython(resync, migrations.RunPython.noop),
    ]
