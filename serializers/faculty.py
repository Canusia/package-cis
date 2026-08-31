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

class DanglingFacultySerializer(serializers.ModelSerializer):
    """Accounts in the faculty group with no FacultyCoordinator record.

    Rows are CustomUser, so every field is flat — unlike FacultySerializer,
    whose user fields are nested.
    """
    last_login = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p',
        read_only=True
    )
    other_roles = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            'id',
            'first_name',
            'last_name',
            'email',
            'primary_phone',
            'last_login',
            'other_roles',
        ]
        datatables_always_serialize = ['id', 'other_roles']

    def get_other_roles(self, obj):
        return [r for r in obj.get_roles() if r != 'faculty']


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
