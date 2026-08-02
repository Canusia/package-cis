from django.contrib.auth import get_user_model
from django.urls import reverse, NoReverseMatch
from rest_framework import serializers

from ..models.note import (
    HighSchoolNote, StudentNote,
    ClassSectionNote,
    TeacherNote,
    TeacherApplicationNote,
    CourseNote
)


def _ethos_log_url_from_meta(meta):
    """Resolve the ethos:ethos_log_detail URL for a note's meta blob, or None."""
    if not meta:
        return None
    log_id = meta.get('ethos_log_id') if isinstance(meta, dict) else None
    if not log_id:
        return None
    try:
        return reverse('ethos:ethos_log_detail', kwargs={'pk': log_id})
    except NoReverseMatch:
        return None

from ..serializers.teacher import CustomUserSerializer, TeacherSerializer
from ..serializers.student import StudentSerializer
from ..serializers.course import CourseSerializer

class CourseNoteSerializer(serializers.ModelSerializer):
    createdby = CustomUserSerializer()
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    course = CourseSerializer()
    
    class Meta:
        model = CourseNote
        fields = '__all__'

class ClassSectionNoteSerializer(serializers.ModelSerializer):

    from ..serializers.class_section import ClassSectionSerializer

    createdby = CustomUserSerializer()
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')

    class_section = ClassSectionSerializer()

    sexy_note = serializers.CharField()
    ethos_log_url = serializers.SerializerMethodField()

    class Meta:
        model = ClassSectionNote
        fields = '__all__'

    def get_ethos_log_url(self, obj):
        return _ethos_log_url_from_meta(obj.meta)

class HighSchoolNoteSerializer(serializers.ModelSerializer):
    createdby = CustomUserSerializer()
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')
    class Meta:
        model = HighSchoolNote
        fields = '__all__'

class StudentNoteSerializer(serializers.ModelSerializer):
    createdby = CustomUserSerializer()
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')
    student = StudentSerializer()
    ethos_log_url = serializers.SerializerMethodField()

    class Meta:
        model = StudentNote
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'note',
            'meta',
            'media',
            'ethos_log_url',
        ]

    def get_ethos_log_url(self, obj):
        return _ethos_log_url_from_meta(obj.meta)


class TeacherNoteSerializer(serializers.ModelSerializer):
    createdby = CustomUserSerializer()
    createdon = serializers.DateTimeField(format='%m/%d/%Y %I:%M %p')
    teacher = TeacherSerializer()

    class Meta:
        model = TeacherNote
        fields = '__all__'

        datatables_always_serialize = [
            'id',
            'note',
            'meta',
            'media'
        ]
