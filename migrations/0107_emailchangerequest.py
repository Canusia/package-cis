# Student self-service email change (#79, ported from nnu#15 / ewu#80).

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0106_upload_media_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailChangeRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('old_email', models.EmailField(max_length=254)),
                ('new_email', models.EmailField(max_length=254)),
                ('code_hash', models.CharField(max_length=64)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='pending', max_length=20)),
                ('attempts_remaining', models.PositiveSmallIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_change_requests', to='cis.student')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
