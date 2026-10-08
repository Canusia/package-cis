from django.contrib.auth import get_user_model
from rest_framework import serializers


from ..models.district import District
from ..models.highschool import HighSchool, HighSchoolTranscript
from ..models.highschool_administrator import (
    HSAdminPerm,
    HSAdministratorPosition, HSAdministratorAccessRequest
)
from ..models.teacher import TeacherHighSchool, TeacherCourseCertificate

from ..serializers.highschool_admin import (
    HSAdministratorSerializer, HSPositionSerializer,
    CustomUserSerializer
)
from ..serializers.teacher import TeacherSerializer
from .course import CourseSerializer

class DistrictSerializer(serializers.ModelSerializer):
    class Meta:
        model = District
        fields = [
            'id',
            'name'
        ]


class DistrictListSerializer(serializers.ModelSerializer):
    """Serializer for the /ce/api/district list endpoint backing the
    /ce/districts/ DataTable. Adds the related-highschool count."""
    num_highschools = serializers.IntegerField(read_only=True)

    class Meta:
        model = District
        fields = [
            'id', 'name', 'address1', 'city', 'state',
            'postal_code', 'primary_phone', 'num_highschools',
        ]


class HighSchoolSerializer(serializers.ModelSerializer):
    district = DistrictSerializer()

    # hs_type stores codes; the table renders this instead. Ordering and
    # search still target the real hs_type column (see highschools_table).
    hs_type_display = serializers.CharField(read_only=True)

    def get_field_names(self, declared_fields, info):
        # fields='__all__' would pick up the HighSchool.campuses M2M, one
        # query per row wherever a school is nested. Keep the pre-link shape.
        names = super().get_field_names(declared_fields, info)
        return [n for n in names if n != 'campuses']

    class Meta:
        model = HighSchool
        fields = '__all__'
        datatables_always_serialize = [
            'city', 'state', 'postal_code'
        ]

class HighSchoolCampusListSerializer(HighSchoolSerializer):
    """HighSchoolSerializer for the CE list, plus the host campus's link.

    Reads ``_campus_links``, which HighSchoolViewSet prefetches filtered to the
    one resolved campus, so it adds no queries per row. Not for nesting.
    """
    campus_building_code = serializers.SerializerMethodField()
    campus_status = serializers.SerializerMethodField()

    def _link(self, obj):
        links = getattr(obj, '_campus_links', None) or []
        return links[0] if links else None

    def get_campus_building_code(self, obj):
        link = self._link(obj)
        return link.building_code if link else ''

    def get_campus_status(self, obj):
        link = self._link(obj)
        return link.status if link else ''

    class Meta(HighSchoolSerializer.Meta):
        ref_name = 'CisHighSchoolCampusList'


class _HighSchoolNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = HighSchool
        fields = ['id', 'name']


class _TermSlimSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    label = serializers.CharField()
    code = serializers.CharField()


class _ReviewerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class HighSchoolTranscriptSerializer(serializers.ModelSerializer):
    # Slim nested shapes: the CE High School Uploads tab lists every school's
    # files, so a full HighSchoolSerializer per row would be wasted work.
    highschool = _HighSchoolNameSerializer()
    uploaded_by = CustomUserSerializer()
    term = _TermSlimSerializer(allow_null=True)
    reviewed_by = _ReviewerSerializer(allow_null=True)

    uploaded_on = serializers.DateTimeField(format='%m/%d/%Y')
    reviewed_on = serializers.DateTimeField(format='%m/%d/%Y', allow_null=True)

    class Meta:
        model = HighSchoolTranscript
        fields = [
            'uploaded_on',
            'uploaded_by',
            'highschool',
            'term',
            'media',
            'description',
            'file_name',
            'reviewed_on',
            'reviewed_by',
            'id'
        ]
        datatables_always_serialize = [
            'id', 'highschool', 'media', 'file_name', 'uploaded_by',
            'term', 'reviewed_on', 'reviewed_by',
        ]


class HighSchoolTeacherSerializer(serializers.ModelSerializer):
    teacher = TeacherSerializer()
    highschool = HighSchoolSerializer()

    class Meta:
        model = TeacherHighSchool
        fields = '__all__'

class HighSchoolAdministratorSerializer(serializers.ModelSerializer):
    hsadmin = HSAdministratorSerializer()
    position = HSPositionSerializer()
    highschool = HighSchoolSerializer()
    # [{codename, campus code or None}] in HSAdminPerm.ALL order (campus None =
    # every campus), not Permission pks.
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = HSAdministratorPosition
        fields = '__all__'

    def get_permissions(self, obj):
        return [{'codename': code, 'campus': campus.code if campus else None}
                for code, campus in obj.grants()]


class TeacherCourseSerializer(serializers.ModelSerializer):
    course = CourseSerializer()
    teacher_highschool = HighSchoolTeacherSerializer()

    since = serializers.DateTimeField(
        format='%Y-%m-%d',
        input_formats=['%Y-%m-%d']
    )
    expires_on = serializers.DateField(format='%Y-%m-%d', required=False, allow_null=True)
    renewal_required_by = serializers.DateField(format='%Y-%m-%d', required=False, allow_null=True)
    last_renewed_on = serializers.DateField(format='%Y-%m-%d', required=False, allow_null=True)
    renewal_due_date = serializers.DateField(format='%Y-%m-%d', read_only=True)

    class Meta:
        model = TeacherCourseCertificate
        fields = '__all__'

class HSAdministratorAccessRequestSerializer(serializers.ModelSerializer):
    highschool = HighSchoolSerializer()
    submittedon = serializers.DateTimeField(
        format='%Y-%m-%d'
    )
    class Meta:
        model = HSAdministratorAccessRequest
        fields = '__all__'
