from django.contrib import admin

from cis.models.settings import Setting

from import_export.admin import ImportExportModelAdmin


@admin.register(Setting)
class SettingAdmin(ImportExportModelAdmin):
    """In multi-campus mode (MC-06, #30) staff see only their own campuses'
    rows and only a superuser may import; single-campus is unchanged."""
    list_display = (
        'key', 'value'
    )

    fields = [
        'key',
        'value'
    ]

    def get_queryset(self, request):
        from cis.campus_context import is_multi_campus
        from cis.campus_gate import get_process_campus_ids
        qs = super().get_queryset(request)
        if not is_multi_campus() or request.user.is_superuser:
            return qs
        return qs.filter(campus__in=get_process_campus_ids(request.user))

    def has_import_permission(self, request, *args, **kwargs):
        from cis.campus_context import is_multi_campus
        if is_multi_campus() and not request.user.is_superuser:
            return False
        return super().has_import_permission(request, *args, **kwargs)
