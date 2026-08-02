from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from cis.models.teacher import (
    Teacher,
    TeacherHighSchool,
    TeacherCourseCertificate
)

class TeacherAdmin(admin.ModelAdmin):
    model = Teacher
    list_display = ['user']
    search_fields = ['user__last_name', 'user__first_name']

class TeacherHighSchoolAdmin(admin.ModelAdmin):
    model = TeacherHighSchool
    list_display = ['teacher', 'highschool', 'status']
    search_fields = ['teacher__user__last_name', 'teacher__user__first_name', 'highschool__name']

class TeacherCourseCertificateAdmin(admin.ModelAdmin):
    model = TeacherCourseCertificate
    list_display = ['teacher_highschool', 'course', 'status']
    search_fields = ['teacher_highschool__teacher__user__last_name', 'teacher_highschool__teacher__user__first_name', 'teacher__highschool__highschool__name', 'course__name']

admin.site.register(Teacher, TeacherAdmin)
admin.site.register(TeacherHighSchool, TeacherHighSchoolAdmin)
admin.site.register(TeacherCourseCertificate, TeacherCourseCertificateAdmin)
