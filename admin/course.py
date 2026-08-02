from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from cis.models.course import (
    Course,
    Cohort,
    Campus,
    CourseAdministrator,
    CourseAppRequirement
)

class CourseAdmin(admin.ModelAdmin):
    model = Course
    list_display = ['name', 'title', 'status']
    search_fields = ['name', 'title']

class CohortAdmin(admin.ModelAdmin):
    model = Cohort
    list_display = ['name', 'status']
    search_fields = ['name']

class CampusAdmin(admin.ModelAdmin):
    model = Campus
    list_display = ['name', 'code']
    search_fields = ['name', 'code']

class CourseAppRequirementAdmin(admin.ModelAdmin):
    model = CourseAppRequirement
    list_display = ['course', 'name', 'status']
    search_fields = ['name', 'course__name']

class CourseAdministratorAdmin(admin.ModelAdmin):
    model = CourseAdministrator
    list_display = ['course', 'user', 'role']
    search_fields = ['course__name', 'role', 'user__first_name', 'user__psid']

admin.site.register(Course, CourseAdmin)
admin.site.register(CourseAppRequirement, CourseAppRequirementAdmin)
admin.site.register(Cohort, CohortAdmin)
admin.site.register(Campus, CampusAdmin)
admin.site.register(CourseAdministrator, CourseAdministratorAdmin)
