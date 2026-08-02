from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from cis.models.student import (
    Student,
    StudentAgreement,
    StudentCampusID,
    StudentRecommendation,
    ParentConsent
)

class ParentConsentAdmin(admin.ModelAdmin):
    model = ParentConsent
    list_display = ['student_name', 'term']
    search_fields = ['user__email', 'user__last_name', 'user__first_name', 'user__psid']

    def student_name(self, obj):
        return f'{obj.student.user.last_name}, {obj.student.user.first_name}'

class StudentRecommendationAdmin(admin.ModelAdmin):
    model = StudentRecommendation
    list_display = ['student_name', 'term']
    search_fields = ['user__email', 'user__last_name', 'user__first_name', 'user__psid']

    def student_name(self, obj):
        return f'{obj.student.user.last_name}, {obj.student.user.first_name}'

class StudentAgreementAdmin(admin.ModelAdmin):
    model = StudentAgreement
    list_display = ['student_name', 'term']
    search_fields = ['user__email', 'user__last_name', 'user__first_name', 'user__psid']

    def student_name(self, obj):
        return f'{obj.student.user.last_name}, {obj.student.user.first_name}'

class StudentAdmin(admin.ModelAdmin):
    model = Student
    list_display = ['student_name', 'student_email']
    search_fields = ['user__email', 'user__last_name', 'user__first_name', 'user__psid']

    def student_name(self, obj):
        return f'{obj.user.last_name}, {obj.user.first_name}'

    def student_email(self, obj):
        return f'{obj.user.email}'

admin.site.register(Student, StudentAdmin)
admin.site.register(ParentConsent, ParentConsentAdmin)
admin.site.register(StudentAgreement, StudentAgreementAdmin)
admin.site.register(StudentRecommendation, StudentRecommendationAdmin)
