from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from cis.models.section import (
    ClassSection,
    ClassSectionNote,
    ClassSectionSyllabi,
    StudentRegistration,
    StudentDropRequest
)

class ClassSectionAdmin(admin.ModelAdmin):
    model = ClassSection
    list_display = ['term', 'class_number', 'course']
    search_fields = ['term__code', 'class_number', 'highschool__name', 'teacher__user__last_name']

class ClassSectionNoteAdmin(admin.ModelAdmin):
    model = ClassSectionNote
    list_display = ['class_section', 'note']
    search_fields = ['class_section__term__code', 'class_section__class_number']

class ClassSectionSyllabiAdmin(admin.ModelAdmin):
    model = ClassSectionSyllabi
    list_display = ['class_sections', 'media', 'uploaded_on']
    search_fields = ['class_sections__term__code', 'class_sections__class_number']

    def class_sections(self, obj):
        return ''.join(', ', [class_section.class_number for class_section in obj.class_sections.all()])

class StudentRegistrationAdmin(admin.ModelAdmin):
    model = StudentRegistration
    list_display = ['created_on', 'student', 'class_section', 'status']
    search_fields = ['student__user__last_name', 'class_section__class_number']

class StudentDropRequestAdmin(admin.ModelAdmin):
    model = StudentDropRequest
    list_display = ['created_on', 'student', 'registration', 'status']
    search_fields = ['student__user__last_name', 'class_section__class_number']

admin.site.register(ClassSection, ClassSectionAdmin)
admin.site.register(ClassSectionNote, ClassSectionNoteAdmin)
admin.site.register(ClassSectionSyllabi, ClassSectionSyllabiAdmin)
admin.site.register(StudentRegistration, StudentRegistrationAdmin)
admin.site.register(StudentDropRequest, StudentDropRequestAdmin)
