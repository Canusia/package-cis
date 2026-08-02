from django.contrib import admin
 
# Register your models here.
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from cis.models.settings import Setting

from import_export.admin import ImportExportModelAdmin

@admin.register(Setting)
class SettingAdmin(ImportExportModelAdmin):
    list_display = (
        'key', 'value'
    )

    fields = [
        'key',
        'value'
    ]