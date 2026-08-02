from django.db import migrations


OLD = 'import_student_id'
NEW = 'import_student_id_from_ethos'


def rename_forward(apps, schema_editor):
    CronTab = apps.get_model('cis', 'CronTab')
    CronTab.objects.filter(command=OLD).update(command=NEW)


def rename_backward(apps, schema_editor):
    CronTab = apps.get_model('cis', 'CronTab')
    CronTab.objects.filter(command=NEW).update(command=OLD)


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0053_add_application_status'),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
