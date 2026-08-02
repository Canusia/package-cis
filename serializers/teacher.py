from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models.teacher import (
    Teacher, TeacherCourseCertificate,
    TeacherUpload, TeacherHighSchool
)


from .course import CourseSerializer
from .highschool_admin import CustomUserSerializer

class TeacherCourseCertificateSkinnySerializer(serializers.ModelSerializer):
    course = CourseSerializer()
   
    since = serializers.DateTimeField(
        format='%Y-%m-%d',
        input_formats=['%Y-%m-%d']
    )

    sexy_status = serializers.CharField(
        read_only=True
    )

    class Meta:
        model = TeacherCourseCertificate
        fields = '__all__'

        datatables_always_serialize = [
            'sexy_status'
        ]
class TeacherSerializer(serializers.ModelSerializer):
    user = CustomUserSerializer()
        
    ce_url = serializers.CharField(
        read_only=True
    )

    faculty_url = serializers.CharField(
        read_only=True
    )
    active_courses = TeacherCourseCertificateSkinnySerializer(many=True)
    active_highschools = serializers.ListField(read_only=True, allow_empty=True)

    class Meta:
        model = Teacher
        fields = '__all__'

        datatables_always_serialize = [
            'ce_url',
            'faculty_url',
        ]

class TeacherHighSchoolSerializer(serializers.ModelSerializer):
    from cis.serializers.highschool import HighSchoolSerializer

    teacher = TeacherSerializer()
    highschool = HighSchoolSerializer()
    
    class Meta:
        model = TeacherHighSchool
        fields = '__all__'

class TeacherCourseCertificateSerializer(serializers.ModelSerializer):
    course = CourseSerializer()
    teacher_highschool = TeacherHighSchoolSerializer()

    class Meta:
        model = TeacherCourseCertificate
        fields = '__all__'

class TeacherUploadTeacherSlimSerializer(serializers.ModelSerializer):
    """Minimal teacher representation for teacher-upload rows (PT-11, Task 3).

    The teacher-uploads DataTables only ever pass ``teacher_id`` *in* as a
    query param; none of the consuming column configs (CE teacher Files tab,
    instructor portal, faculty portal) read any ``teacher.*`` field back out of
    a row. The previous nesting of the full ``TeacherSerializer`` ->
    ``CustomUserSerializer`` therefore leaked names, emails, phones, addresses,
    DOB, etc. for every row to no purpose. Expose only the teacher id plus a
    non-PII display string, in case a future column needs to label a row.
    """
    name = serializers.CharField(source='__str__', read_only=True)

    class Meta:
        model = Teacher
        fields = ['id', 'name']

class TeacherUploadSerializer(serializers.ModelSerializer):
    """Serializer for the /ce/api/teacher-uploads endpoint (PT-11).

    Deliberately enumerates fields instead of ``'__all__'`` so the response is
    limited to what the consuming DataTables actually render (media_type,
    description, the download link, id) plus a slim, non-PII teacher stub.

    ``media`` is NOT the raw FileField (which renders a pre-signed S3 URL that is
    independently downloadable by any holder within the signature window).
    Instead it returns the relative URL of the authorized ``download`` action,
    which re-checks the caller's role scope at request time (PT-11, Task 4).
    """
    teacher = TeacherUploadTeacherSlimSerializer(read_only=True)
    media = serializers.SerializerMethodField()

    class Meta:
        model = TeacherUpload
        fields = [
            'id', 'media_type', 'description', 'media', 'uploaded_on', 'teacher',
        ]

    def get_media(self, obj):
        """Relative URL of the authorized download action (no pre-signed URL)."""
        from django.urls import reverse
        if not obj.media:
            return None
        return reverse('cis:teacher-uploads-download', kwargs={'pk': obj.pk})

class TeacherUploadListSerializer(serializers.ModelSerializer):
    """Flat serializer for the CE Instructors > Files tab.

    Deliberately does NOT nest ``TeacherSerializer``: that pulls
    ``active_courses`` / ``active_highschools`` per row. Acceptable for one
    instructor's file list, not for a table spanning every instructor.

    Like ``TeacherUploadSerializer``, ``media`` is the relative URL of the
    authorized ``download`` action, never ``obj.media.url``. PrivateMediaStorage
    is S3 with ``AWS_QUERYSTRING_AUTH`` on, so the raw URL is a pre-signed link
    that anyone who obtains it can replay without authentication until it
    expires. The download action re-checks the caller's role scope (PT-11).

    ``teacher_*`` fields use real ORM paths as their ``source`` so the
    DataTables ``data-name`` attributes can order and search on them; the flat
    JSON key stays the ``data-data``. ``file_name`` is a model property, so its
    column must be declared non-orderable / non-searchable in the template.
    """
    teacher_id = serializers.CharField(source='teacher.id', read_only=True)
    teacher_last_name = serializers.CharField(
        source='teacher.user.last_name', read_only=True)
    teacher_first_name = serializers.CharField(
        source='teacher.user.first_name', read_only=True)
    teacher_email = serializers.CharField(
        source='teacher.user.email', read_only=True)
    ce_url = serializers.CharField(source='teacher.ce_url', read_only=True)
    file_name = serializers.CharField(read_only=True)
    media = serializers.SerializerMethodField()
    uploaded_on = serializers.DateTimeField(format='%m/%d/%Y', read_only=True)

    class Meta:
        model = TeacherUpload
        fields = [
            'id', 'media_type', 'description', 'file_name', 'media',
            'uploaded_on', 'teacher_id', 'teacher_last_name',
            'teacher_first_name', 'teacher_email', 'ce_url',
        ]

        datatables_always_serialize = [
            'id', 'media', 'ce_url', 'teacher_id',
        ]

    def get_media(self, obj):
        """Relative URL of the authorized download action (no pre-signed URL)."""
        from django.urls import reverse
        if not obj.media:
            return None
        return reverse('cis:teacher-uploads-download', kwargs={'pk': obj.pk})
