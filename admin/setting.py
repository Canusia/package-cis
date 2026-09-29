from django.contrib import admin

from cis.models.settings import Setting

from import_export.admin import ImportExportModelAdmin


@admin.register(Setting)
class SettingAdmin(ImportExportModelAdmin):
    """In multi-campus mode (MC-06, #30) staff see only their own campuses'
    rows and only a superuser may import; single-campus is unchanged."""
    # campus: null means one row shared by every campus (MC-05). Only a
    # superuser may move a row between campuses.
    list_display = (
        'key', 'campus_label', 'value'
    )
    list_filter = ('campus',)
    list_select_related = ('campus',)
    search_fields = ('key',)

    fields = [
        'key',
        'campus',
        'value'
    ]

    @admin.display(description='Campus', ordering='campus__name')
    def campus_label(self, obj):
        return obj.campus.name if obj.campus_id else 'Shared (all campuses)'

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.append('campus')
        return readonly

    def save_model(self, request, obj, form, change):
        # A superuser's choice, including "shared" (no campus), is final:
        # without this Setting.save() would refill a campus-scoped key's
        # campus from the host being served.
        if 'campus' in form.cleaned_data:
            obj._campus_given = True
        super().save_model(request, obj, form, change)

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
