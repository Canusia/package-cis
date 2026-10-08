"""Copy StudentFerpa.campus (JSON) into legacy_campus before 0104 drops it (#65)."""
from django.db import migrations
from django.db.models import F


def forward(apps, schema_editor):
    StudentFerpa = apps.get_model('cis', 'StudentFerpa')
    StudentFerpa.objects.update(legacy_campus=F('campus'))


def backward(apps, schema_editor):
    StudentFerpa = apps.get_model('cis', 'StudentFerpa')
    for row in StudentFerpa.objects.only('id', 'legacy_campus').iterator():
        StudentFerpa.objects.filter(pk=row.pk).update(
            campus=row.legacy_campus if row.legacy_campus is not None else [])


class Migration(migrations.Migration):

    dependencies = [('cis', '0102_studentferpa_legacy_campus')]

    operations = [migrations.RunPython(forward, backward)]
