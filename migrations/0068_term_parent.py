import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0067_add_course_certificates_nav'),
    ]

    operations = [
        migrations.AddField(
            model_name='term',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sub_terms', to='cis.term'),
        ),
    ]
