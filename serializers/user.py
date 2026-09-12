"""Serializers for the CE account tables under /ce/users/."""
from django.contrib.auth import get_user_model

from rest_framework import serializers


class StaffUserSerializer(serializers.ModelSerializer):
    """Rows for the /ce/users/ DataTable.

    Rows are CustomUser, so every field is flat — unlike StudentSerializer,
    whose user fields are nested. The matching data-name paths therefore live
    in myce_tenant_configs/services/users_table.py as bare field names.
    """
    created_at = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p',
        read_only=True
    )
    last_login = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p',
        read_only=True
    )

    class Meta:
        model = get_user_model()
        fields = [
            'id',
            'first_name',
            'last_name',
            'email',
            'psid',
            'is_active',
            'created_at',
            'last_login',
        ]
        datatables_always_serialize = ['id']


class LockedUserSerializer(serializers.ModelSerializer):
    """Rows for the /ce/users/locked/ DataTable.

    Locked accounts are not role-specific -- a locked student is as locked as
    a locked CE staffer -- so these rows span every group, and `roles` is what
    tells them apart. It is derived from the groups m2m, which means it has no
    single ORM path: the matching header in
    myce_tenant_configs/services/locked_users_table.py marks that column
    unorderable and unsearchable, and points data-name at `id` instead.

    Rows are flat CustomUser, like StaffUserSerializer above.
    """
    last_login = serializers.DateTimeField(
        format='%m/%d/%Y %I:%M %p',
        read_only=True
    )
    roles = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            'id',
            'first_name',
            'last_name',
            'email',
            'psid',
            'roles',
            'failed_login_attempts',
            'last_login',
            'is_active',
        ]
        datatables_always_serialize = ['id', 'roles']

    def get_roles(self, obj):
        return obj.get_roles()
