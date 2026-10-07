"""Copy the legacy HSAdministratorPosition.meta flags into permissions.

Only manage_student_recommendation and manage_roster_verification carry over
(any casing of 'yes'); the seven new permissions start off for everyone and
are granted by CE. Django creates Meta.permissions rows after migrate
finishes, so they are created here (same as 0090_ssn_permissions). The meta
keys are left in place for rollback; nothing reads them after this.
"""
from django.db import migrations

PERMISSIONS = (
    ('can_manage_student_recommendation', 'Can manage student recommendations'),
    ('can_verify_roster', 'Can verify class rosters'),
    ('can_bulk_upload_students', 'Can bulk upload students'),
    ('can_bulk_enroll', 'Can bulk enroll'),
    ('can_bulk_upload_supporting_docs', 'Can upload supporting documents'),
    ('can_manage_school_personnel', 'Can manage school personnel'),
    ('can_manage_future_sections', 'Can manage future sections'),
    ('can_submit_drop_requests', 'Can submit drop requests'),
    ('can_submit_grades', 'Can submit grades'),
)
LEGACY = {
    'manage_student_recommendation': 'can_manage_student_recommendation',
    'manage_roster_verification': 'can_verify_roster',
}


def _permissions(apps):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    content_type, _ = ContentType.objects.get_or_create(
        app_label='cis', model='hsadministratorposition')
    return {
        codename: Permission.objects.get_or_create(
            content_type=content_type, codename=codename, defaults={'name': name})[0]
        for codename, name in PERMISSIONS
    }


def forward(apps, schema_editor):
    perms = _permissions(apps)
    Position = apps.get_model('cis', 'HSAdministratorPosition')
    Through = Position.permissions.through

    rows = []
    for position in Position.objects.only('id', 'meta').iterator():
        meta = position.meta if isinstance(position.meta, dict) else {}
        for key, codename in LEGACY.items():
            if str(meta.get(key) or '').strip().lower() == 'yes':
                rows.append(Through(hsadministratorposition_id=position.id,
                                    permission_id=perms[codename].id))
    Through.objects.bulk_create(rows, ignore_conflicts=True)


def backward(apps, schema_editor):
    Position = apps.get_model('cis', 'HSAdministratorPosition')
    Through = Position.permissions.through
    ours = Through.objects.filter(
        permission__content_type__app_label='cis',
        permission__content_type__model='hsadministratorposition')

    held = set(ours.filter(permission__codename__in=LEGACY.values())
               .values_list('hsadministratorposition_id', 'permission__codename'))
    for position in Position.objects.iterator():
        meta = dict(position.meta) if isinstance(position.meta, dict) else {}
        for key, codename in LEGACY.items():
            meta[key] = 'Yes' if (position.id, codename) in held else 'No'
        position.meta = meta
        position.save(update_fields=['meta'])
    ours.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0100_hsadministratorposition_permissions'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
