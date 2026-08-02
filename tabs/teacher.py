"""Teacher (instructor) detail-page tab content functions (see cis/tabs/course.py).
Eager-imported by myce/component_registry/teacher.py so decorators run.
"""
from myce.component_registry.teacher import teacher_tabs  # noqa: F401


@teacher_tabs.tab(slug='sections', title='Sections Taught', order=30,
                  template='cis/teachers/tabs/_sections.html')
def sections_tab(request, record):
    from cis.services.table_configs import get_table_config
    return {'sections_table': get_table_config('sections_table').build_config(
        variant='instructor_detail',
        api_url=f'/ce/api/class_section?format=datatables&teacher_id={record.id}&term=-1')}


@teacher_tabs.tab(slug='visits', title='Visit(s)', order=60,
                  template='cis/teachers/tabs/_visits.html')
def visits_tab(request, record):
    return {}


@teacher_tabs.tab(slug='drop_wd', title='Drop Requests', order=80,
                  template='cis/teachers/tabs/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


@teacher_tabs.tab(slug='courses', title='Course Cert(s)', order=20,
                  template='cis/teachers/tabs/_courses.html')
def courses_tab(request, record):
    return {'teacher_course_certificates_api': '/ce/api/teacher-course'}


@teacher_tabs.tab(slug='notes', title='Notes', order=70,
                  template='cis/teachers/tabs/_notes.html')
def notes_tab(request, record):
    return {'teacher_notes_api': '/ce/api/teacher-notes'}


@teacher_tabs.tab(slug='highschools', title='High Schools', order=10,
                  template='cis/teachers/tabs/_highschools.html', lazy=False, active=True)
def highschools_tab(request, record):
    from cis.models.teacher import TeacherHighSchool
    return {'highschools': TeacherHighSchool.objects.filter(teacher=record.id)}


@teacher_tabs.tab(slug='ed_background', title='Ed. Background', order=40,
                  template='cis/teachers/tabs/_ed_background.html', lazy=False)
def ed_background_tab(request, record):
    from cis.forms.teacher import EdBgForm
    if request.method == 'POST' and request.POST.get('action') == 'edit_ed_bg':
        form = EdBgForm(record.user, request.POST)
        form.is_valid()
    else:
        form = EdBgForm(user=record.user)
    return {'ed_bg': record.user.education_background, 'ed_bg_form': form}


@teacher_tabs.tab(slug='files', title='Files', order=50,
                  template='cis/teachers/tabs/_files.html', lazy=False)
def files_tab(request, record):
    from cis.forms.teacher import TeacherUploadForm
    if request.method == 'POST' and request.POST.get('action') == 'upload_file':
        form = TeacherUploadForm(record, request.POST, request.FILES)
        form.is_valid()
    else:
        form = TeacherUploadForm(teacher=record)
    return {'file_upload_form': form, 'teacher_uploads_api': '/ce/api/teacher-uploads'}


@teacher_tabs.tab(slug='migrate', title='Migrate Record', order=90,
                  template='cis/teachers/tabs/_migrate.html', lazy=False)
def migrate_tab(request, record):
    from cis.forms.teacher import MigrateForm
    if request.method == 'POST' and request.POST.get('action') == 'migrate_position':
        form = MigrateForm(record=record, data=request.POST)
        form.is_valid()
    else:
        form = MigrateForm(record=record)
    return {'migration_form': form}
