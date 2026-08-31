from django.contrib.auth import get_user_model
from rest_framework import serializers

from ..models.highschool_administrator import (
    HSAdministrator, HSPosition, HSAdministratorPosition,
    HSAdministratorAccessRequest
)

# from ..serializers.highschool import HighSchoolSerializer

class CustomUserSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(
        format='%Y-%m-%d %I:%M:%S %p'
    )
    last_login = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p',
        read_only=True
    )

    class Meta:
        model = get_user_model()
        fields = [
            'first_name',
            'last_name',
            'email',
            'username',
            'primary_phone',
            'psid',
            'created_at',
            'last_login',
            'suffix',
            'middle_name',
            'address1',
            'city',
            'date_of_birth',
            'state','postal_code','county'
        ]

class HSAdministratorSerializer(serializers.ModelSerializer):
    user = CustomUserSerializer()
    ce_url = serializers.CharField(
        read_only=True
    )
    # Populated by the annotation in HSAdministratorViewSet.get_queryset.
    # required=False keeps the field optional when this serializer is nested
    # inside HighSchoolAdministratorSerializer, whose instances are un-annotated.
    school_count = serializers.IntegerField(
        read_only=True,
        required=False
    )

    class Meta:
        model = HSAdministrator
        fields = '__all__'

        datatables_always_serialize = [
            'ce_url'
        ]

class HSPositionSerializer(serializers.ModelSerializer):
    hsadministratorposition_count = serializers.IntegerField(
        read_only=True
    )
    class Meta:
        model = HSPosition
        fields = [
            'id',
            'name',
            'hsadministratorposition_count'
        ]


class SlimUserSerializer(serializers.ModelSerializer):
    """Minimal user fields for admin position display."""
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']


class HSAdministratorPositionSerializer(serializers.ModelSerializer):
    """Serializer for administrator positions for DataTables display."""
    id = serializers.UUIDField(read_only=True)
    highschool_id = serializers.UUIDField(source='highschool.id')
    highschool_name = serializers.CharField(source='highschool.name')
    position_id = serializers.UUIDField(source='position.id')
    position_name = serializers.CharField(source='position.name')
    admin_name = serializers.SerializerMethodField()
    admin_email = serializers.EmailField(source='hsadmin.user.email')

    class Meta:
        model = HSAdministratorPosition
        fields = [
            'id',
            'highschool_id',
            'highschool_name',
            'position_id',
            'position_name',
            'admin_name',
            'admin_email',
            'status'
        ]
        datatables_always_serialize = ['id', 'highschool_id', 'position_id']

    def get_admin_name(self, obj):
        user = obj.hsadmin.user
        return f"{user.last_name}, {user.first_name}"


class DanglingHSAdminSerializer(serializers.ModelSerializer):
    """Accounts in the highschool_admin group with no HSAdministrator record.

    Rows are CustomUser, so every field is flat — unlike HSAdministratorSerializer,
    whose user fields are nested. The table config's data-name values are the
    bare column names for that reason.
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
        return [r for r in obj.get_roles() if r != 'highschool_admin']
