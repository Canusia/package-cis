# Raise the cis private-media FileFields from Django's default max_length of
# 100 to 255, so upload names keep more of the original filename
# (Canusia/package-cis#73). On PostgreSQL, making a varchar longer only
# changes the catalog: no table rewrite and no index rebuild.

import cis.models.crontab
import cis.storage_backend
import cis.utils
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cis', '0105_studentferpa_campus_backfill'),
    ]

    operations = [
        migrations.AlterField(
            model_name='applicantrecommendation',
            name='upload',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.recommendation_upload_path),
        ),
        migrations.AlterField(
            model_name='applicationupload',
            name='upload',
            field=models.FileField(blank=True, max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.teacher_app_upload_path),
        ),
        migrations.AlterField(
            model_name='classsectionsyllabi',
            name='media',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.syllabus_upload_path),
        ),
        migrations.AlterField(
            model_name='courseupload',
            name='media',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.course_files_upload_path),
        ),
        migrations.AlterField(
            model_name='cronlog',
            name='log_file',
            field=models.FileField(blank=True, max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.models.crontab.cron_log_upload_path),
        ),
        migrations.AlterField(
            model_name='highschooltranscript',
            name='media',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.hs_transcript_upload_path),
        ),
        migrations.AlterField(
            model_name='studentnote',
            name='media',
            field=models.FileField(blank=True, max_length=255, null=True, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.student_notes_media_upload_path),
        ),
        migrations.AlterField(
            model_name='studentrecommendation',
            name='upload',
            field=models.FileField(blank=True, max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.student_recommendation_upload_path),
        ),
        migrations.AlterField(
            model_name='studentsupportingdocument',
            name='media',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.student_supporting_doc_upload_path),
        ),
        migrations.AlterField(
            model_name='studenttuitionassistancedocument',
            name='media',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.student_tuition_assistance_upload_path),
        ),
        migrations.AlterField(
            model_name='teachernote',
            name='media',
            field=models.FileField(blank=True, max_length=255, null=True, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.teacher_notes_media_upload_path),
        ),
        migrations.AlterField(
            model_name='teacherupload',
            name='media',
            field=models.FileField(max_length=255, storage=cis.storage_backend.PrivateMediaStorage(), upload_to=cis.utils.teacher_files_upload_path),
        ),
    ]
