"""Course detail-page tab content functions.

Each function is registered with `@course_tabs.tab(...)` and returns a context
dict (rendered into the declared template) or an HttpResponse. This module is
eager-imported by myce/component_registry/course.py so the decorators run.
"""
from django.shortcuts import get_object_or_404

from myce.component_registry.course import course_tabs  # noqa: F401


def _offerings_count(record, user):
    from cis.models import ClassSection
    return ClassSection.objects.filter(course=record).count() or None


@course_tabs.tab(slug='class_sections', title='Offerings', order=30,
                 template='cis/course/tabs/_offerings.html',
                 badge=_offerings_count)
def offerings_tab(request, record):
    from cis.services.table_configs import get_table_config
    build = get_table_config('sections_table').build_config
    return {'sections_table': build(
        variant='course_detail',
        api_url=f'/ce/api/class_section/?term=-1&course={record.id}&format=datatables',
    )}


@course_tabs.tab(slug='change_history', title='Change History', order=110,
                 template='cis/course/tabs/_change_history.html')
def change_history_tab(request, record):
    return {
        'history_table_id': 'course_history',
        'history_show_source_badge': False,
        'history_api_url': f'/ce/api/course-history/?course_id={record.id}',
    }


@course_tabs.tab(slug='instructors', title='Instructor(s)', order=20,
                 template='cis/course/tabs/_instructors.html')
def instructors_tab(request, record):
    from cis.services.table_configs import get_table_config
    build = get_table_config('instructors_table').build_config
    return {'instructors_table': build(
        variant='course_instructors',
        api_url=f'/ce/api/teacher-course/?course_id={record.id}&format=datatables',
        details_prefix='/ce/instructor/',
    )}


@course_tabs.tab(slug='drop_wd', title='Drop Requests', order=40,
                 template='cis/course/tabs/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


@course_tabs.tab(slug='visits', title='Visit(s)', order=90,
                 template='cis/course/tabs/_visits.html')
def visits_tab(request, record):
    return {}


@course_tabs.tab(slug='registrations_summary', title='Registrations Summary', order=50,
                 template='cis/course/tabs/_registrations_summary.html')
def registrations_summary_tab(request, record):
    return {'registration_summary_api_url':
            f'/ce/api/registration-summary/?course_id={record.id}&format=datatables'}


@course_tabs.tab(slug='notes', title='Notes', order=100,
                 template='cis/course/tabs/_notes.html')
def notes_tab(request, record):
    return {'course_notes_api': '/ce/api/course-notes'}


@course_tabs.tab(slug='details', title='Details', order=10,
                 template='cis/course/tabs/_details.html', lazy=False)
def details_tab(request, record):
    from cis.forms.course import CourseForm
    if request.method == 'POST' and request.POST.get('action') == 'save_course':
        # Bind to POST and call is_valid() purely to populate form.errors for
        # re-display (return value intentionally ignored). CourseForm has no
        # custom clean(), so this is read-only; detail() owns the actual save.
        form = CourseForm(request.POST, instance=record)
        form.is_valid()
    else:
        form = CourseForm(instance=record)
    return {'form': form}


@course_tabs.tab(slug='app_documents', title='Teacher App. Doc(s)', order=60,
                 template='cis/course/tabs/_app_documents.html', lazy=False, active=True)
def app_documents_tab(request, record):
    from cis.models.course import CourseAppRequirement
    from cis.forms.course import CourseAppRequirementForm
    course_app_id = request.GET.get('course_app_id')
    course_app_req = (get_object_or_404(CourseAppRequirement, pk=course_app_id)
                      if course_app_id else None)
    if request.method == 'POST' and request.POST.get('action') == 'save_course_app_req':
        form = CourseAppRequirementForm(request.POST, instance=course_app_req)
        form.is_valid()
    else:
        form = CourseAppRequirementForm(instance=course_app_req)
    return {'app_reqs': CourseAppRequirement.objects.filter(course=record),
            'course_app_req_form': form}


@course_tabs.tab(slug='administrators', title='Administrator(s)', order=70,
                 template='cis/course/tabs/_administrators.html', lazy=False)
def administrators_tab(request, record):
    from cis.models.course import CourseAdministrator
    return {'administrators': CourseAdministrator.objects.filter(course=record)}


@course_tabs.tab(slug='files', title='Files', order=80,
                 template='cis/course/tabs/_files.html', lazy=False)
def files_tab(request, record):
    from cis.forms.course import CourseUploadForm
    if request.method == 'POST' and request.POST.get('action') == 'upload_file':
        form = CourseUploadForm(record, request.user, request.POST, request.FILES)
        form.is_valid()
    else:
        form = CourseUploadForm(course=record, user=request.user)
    return {'file_upload_form': form, 'course_uploads_api': '/ce/api/course-uploads'}


@course_tabs.tab(slug='migrate', title='Migrate Record', order=120,
                 template='cis/course/tabs/_migrate.html', lazy=False)
def migrate_tab(request, record):
    from cis.forms.course import MigrateForm
    if request.method == 'POST' and request.POST.get('action') == 'migrate_course':
        form = MigrateForm(record=record, data=request.POST)
        form.is_valid()
    else:
        form = MigrateForm(record=record)
    return {'migration_form': form}
