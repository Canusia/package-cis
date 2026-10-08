"""StudentFerpa.campus becomes an FK to Campus; freshness moves onto the row (#65).

The JSON `campus` was copied to legacy_campus by 0103. Remove + Add rather than
AlterField: Postgres cannot cast a JSON column to a UUID foreign key.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0103_studentferpa_copy_legacy_campus'),
    ]

    operations = [
        # A default first, so the reverse of RemoveField can re-add the JSON
        # column on a non-empty table; 0103's backward then refills it.
        migrations.AlterField(
            model_name='studentferpa', name='campus',
            field=models.JSONField(default=list)),
        migrations.AlterUniqueTogether(name='studentferpa', unique_together=set()),
        migrations.RemoveField(model_name='studentferpa', name='campus'),
        migrations.AddField(
            model_name='studentferpa', name='campus',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='ferpa_records', to='cis.campus')),
        migrations.AddField(
            model_name='studentferpa', name='completed_for',
            field=models.JSONField(blank=True, default=list)),
        migrations.AddField(
            model_name='studentferpa', name='completed_on',
            field=models.DateField(blank=True, null=True)),
        migrations.AddConstraint(
            model_name='studentferpa',
            constraint=models.UniqueConstraint(
                fields=('student', 'campus'), name='studentferpa_unique_student_campus')),
    ]
