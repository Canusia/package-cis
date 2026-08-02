"""High School detail-page tab content functions (see cis/tabs/course.py).
Eager-imported by myce/component_registry/highschool.py so decorators run.
"""
from myce.component_registry.highschool import highschool_tabs  # noqa: F401


def _sections_build(record):
    from cis.services.table_configs import get_table_config
    return get_table_config('sections_table').build_config(
        variant='highschool_detail',
        api_url=f'/ce/api/class_section/?term=-1&highschool_id={record.id}&format=datatables')


def _instructors_build(record):
    from cis.services.table_configs import get_table_config
    return get_table_config('instructors_table').build_config(
        variant='highschool_instructors',
        api_url=f'/ce/api/highschool-teacher/?highschool_id={record.id}&format=datatables',
        details_prefix='/ce/instructor/')


@highschool_tabs.tab(slug='instructors', title='Instructors', order=20,
                     template='cis/highschools/tabs/_instructors.html', active=True)
def instructors_tab(request, record):
    return {'instructors_table': _instructors_build(record)}


@highschool_tabs.tab(slug='class_sections', title='Class Offerings', order=30,
                     template='cis/highschools/tabs/_class_sections.html')
def class_sections_tab(request, record):
    return {'sections_table': _sections_build(record)}


@highschool_tabs.tab(slug='registrations_summary', title='Registrations Summary', order=40,
                     template='cis/highschools/tabs/_registrations_summary.html')
def registrations_summary_tab(request, record):
    return {'registration_summary_api_url':
            f'/ce/api/registration-summary/?highschool_id={record.id}&format=datatables'}


@highschool_tabs.tab(slug='drop_wd', title='Drop Requests', order=50,
                     template='cis/highschools/tabs/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


@highschool_tabs.tab(slug='administrators', title='Administrators', order=60,
                     template='cis/highschools/tabs/_administrators.html')
def administrators_tab(request, record):
    return {'administrator_api_url':
            f'/ce/api/highschool-administrator/?highschool_id={record.id}&format=datatables'}


@highschool_tabs.tab(slug='visits', title='Visits', order=70,
                     template='cis/highschools/tabs/_visits.html')
def visits_tab(request, record):
    return {}


@highschool_tabs.tab(slug='applicants', title='Applicants', order=80,
                     template='cis/highschools/tabs/_applicants.html')
def applicants_tab(request, record):
    from django.utils.safestring import mark_safe
    # mark_safe: rendered in a <script> string (ajax: '{{ teacher_app_api_url }}');
    # without it Django escapes & -> &amp;, mangling the highschool_id filter so
    # the tab would show every high school's applications.
    return {'teacher_app_api_url': mark_safe(
        f'/ce/api/teacher_application?format=datatables&highschool_id={record.id}')}


@highschool_tabs.tab(slug='transcripts', title='Transcripts', order=85,
                     template='cis/highschools/tabs/_transcripts.html')
def transcripts_tab(request, record):
    from cis.forms.highschool import HSTranscriptUploadForm
    return {'transcripts_api_url':
            f'/ce/api/highschool-transcript/?highschool_id={record.id}&format=datatables',
            'transcript_upload_form': HSTranscriptUploadForm()}


@highschool_tabs.tab(slug='notes', title='Notes', order=90,
                     template='cis/highschools/tabs/_notes.html')
def notes_tab(request, record):
    return {'note_api_url':
            f'/ce/api/highschool-note/?highschool_id={record.id}&format=datatables'}


@highschool_tabs.tab(slug='details', title='Details', order=10,
                     template='cis/highschools/tabs/_details.html', lazy=False)
def details_tab(request, record):
    from cis.forms.highschool import HSModelForm
    if (request.method == 'POST'
            and request.POST.get('action') not in ('migrate_highschool', 'upload_transcript')):
        form = HSModelForm(request.POST, instance=record)
        form.is_valid()
    else:
        form = HSModelForm(instance=record)
    return {'form': form}


@highschool_tabs.tab(slug='migrate', title='Migrate Record', order=100,
                     template='cis/highschools/tabs/_migrate.html', lazy=False)
def migrate_tab(request, record):
    from cis.forms.highschool import MigrateForm
    if request.method == 'POST' and request.POST.get('action') == 'migrate_highschool':
        form = MigrateForm(record=record, data=request.POST)
        form.is_valid()
    else:
        form = MigrateForm(record=record)
    return {'migration_form': form}


@highschool_tabs.tab(slug='change_history', title='Change History', order=200,
                     template='cis/highschools/tabs/_change_history.html')
def change_history_tab(request, record):
    return {
        'history_table_id': 'highschool_history',
        'history_show_source_badge': False,
        'history_api_url': f'/ce/api/highschool-history/?highschool_id={record.id}',
    }
