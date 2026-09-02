from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from cis.models.sis import (
    SIS_Log,
)

class SIS_LogAdmin(admin.ModelAdmin):
    model = SIS_Log
    list_display = ['id', 'sent_on', 'message', 'response']
    # search_fields = ['user__email', 'user__last_name', 'user__first_name', 'user__psid']

    # def student_name(self, obj):
    #     return f'{obj.student.user.last_name}, {obj.student.user.first_name}'

admin.site.register(SIS_Log, SIS_LogAdmin)
