from django.contrib.auth import get_user_model
from rest_framework import serializers

from cis.models.faculty import FacultyCoordinator
from cis.models.course import CourseAdministrator

from .term import AcademicYearSerializer
from .highschool_admin import CustomUserSerializer
from .highschool import HighSchoolSerializer
from .course import CourseSerializer

class FacultySerializer(serializers.ModelSerializer):
    user = CustomUserSerializer()
    ce_url = serializers.CharField(
        read_only=True
    )

    class Meta:
        model = FacultyCoordinator
        fields = '__all__'

        datatables_always_serializer = [
            'id',
            'ce_url'
        ]

class CourseAdministratorSerializer(serializers.ModelSerializer):
    course = CourseSerializer()
    user = CustomUserSerializer()

    faculty_id = serializers.CharField(
        read_only=True
    )

    class Meta:
        model = CourseAdministrator
        fields = '__all__'
        ref_name = 'CisCourseAdministrator'

        datatables_always_serialize = [
            'faculty_id'
        ]
