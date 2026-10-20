import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0108_hide_packaged_portal_settings'),
    ]

    operations = [
        migrations.CreateModel(
            name='FacultyCourseAssignment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_on', models.DateTimeField(auto_now_add=True)),
                ('academic_year', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='faculty_course_assignments', to='cis.academicyear')),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='faculty_course_assignments', to='cis.course')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='faculty_course_assignments_created', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='faculty_course_assignments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'course', 'academic_year')},
            },
        ),
    ]
