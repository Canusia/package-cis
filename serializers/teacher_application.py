from django.contrib.auth import get_user_model
from rest_framework import serializers


from cis.models.teacher_applicant import (
    TeacherApplicant,
    TeacherApplication,
    ApplicantSchoolCourse,
    ApplicantRecommendation,
    ApplicationUpload,
    ApplicantCourseReviewer
)

from .term import AcademicYearSerializer
from .highschool_admin import CustomUserSerializer
from .highschool import HighSchoolSerializer
from .course import CourseSerializer

class TeacherApplicationSerializer(serializers.ModelSerializer):
    user = CustomUserSerializer()
    assigned_to = CustomUserSerializer()
    highschool = HighSchoolSerializer()
    createdon = serializers.DateField(format='%Y-%m-%d')

    courses = serializers.CharField(
        read_only=True
    )

    ce_url = serializers.CharField(
        read_only=True
    )
    
    attending_si_year = serializers.CharField(
        read_only=True
    )

    missing_items = serializers.ListField(read_only=True, allow_empty=True)

    class Meta:
        model = TeacherApplication
        fields = '__all__'
        ref_name = 'CisTeacherApplication'

        datatables_always_serializer = [
            'id',
            'ce_url',
            'missing_items',
            'attending_si_year',
        ]

class ApplicantSchoolCourseSerializer(serializers.ModelSerializer):
    teacherapplication = TeacherApplicationSerializer()
    course = CourseSerializer()
    highschool = HighSchoolSerializer()
    starting_academic_year = AcademicYearSerializer()

    class Meta:
        model = ApplicantSchoolCourse
        fields = '__all__'
        ref_name = 'CisApplicantSchoolCourse'
        
class ApplicantCourseReviewerSerializer(serializers.ModelSerializer):
    reviewer = CustomUserSerializer()
    application_course = ApplicantSchoolCourseSerializer()

    assigned_on = serializers.DateField(format='%m/%d/%Y')
    class Meta:
        model = ApplicantCourseReviewer
        fields = '__all__'
        ref_name = 'CisApplicantCourseReviewer'
