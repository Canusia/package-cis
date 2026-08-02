"""ClassSection detail-page tab content functions.

Each function is registered with @class_section_tabs.tab(...) and returns a
context dict (rendered into the declared template) or an HttpResponse. This
module is eager-imported by myce/component_registry/class_section.py so the
decorators run.
"""
from myce.component_registry.class_section import class_section_tabs  # noqa: F401


# ---------------------------------------------------------------------------
# Task 2 — LAZY tabs
# ---------------------------------------------------------------------------

@class_section_tabs.tab(slug='details', title='Details', order=10,
                        template='cis/sections/tabs/_details.html')
def details_tab(request, record):
    return {}


def _students_count(record, user):
    from cis.models.section import StudentRegistration
    return StudentRegistration.objects.filter(class_section=record).count() or None


@class_section_tabs.tab(slug='students', title='Students in Class', order=20,
                        template='cis/sections/tabs/_students.html',
                        active=True, badge=_students_count)
def students_tab(request, record):
    from cis.services.table_configs import get_table_config
    from django.db.models import Count
    from cis.models.section import StudentRegistration
    build = get_table_config('registrations_table').build_config
    status_counts = (
        StudentRegistration.objects.filter(class_section=record)
        .values('status')
        .annotate(count=Count('id'))
        .order_by('status')
    )
    status_map = dict(StudentRegistration.STATUS_OPTIONS)
    roster_badges = [
        {'status': status_map.get(sc['status'], sc['status']),
         'status_code': sc['status'],
         'count': sc['count']}
        for sc in status_counts
    ]
    roster_total = sum(sc['count'] for sc in status_counts)
    return {
        'registrations_table': build(
            variant='section_detail',
            api_url=f'/ce/api/registration?format=datatables&class_section={record.id}',
        ),
        'roster_badges': roster_badges,
        'roster_total': roster_total,
    }


@class_section_tabs.tab(slug='drop_wd', title='Drop Requests', order=30,
                        template='cis/sections/tabs/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


@class_section_tabs.tab(slug='visits', title='Visit(s)', order=50,
                        template='cis/sections/tabs/_visits.html')
def visits_tab(request, record):
    return {}


@class_section_tabs.tab(slug='syllabi', title='Syllabi', order=40,
                        template='cis/sections/tabs/_syllabi.html', lazy=False)
def syllabi_tab(request, record):
    from cis.forms.section import SectionSyllabiForm
    if request.method == 'POST' and request.POST.get('add_syllabi', None):
        form = SectionSyllabiForm(
            record.term, record.teacher, record.course,
            request.POST, request.FILES)
        form.is_valid()  # bind errors for re-display; detail() owns the save
    else:
        form = SectionSyllabiForm(
            term=record.term, teacher=record.teacher, course=record.course)
    syllabi = record.get_syllabi()
    return {'syllabi_form': form, 'syllabi': syllabi}


@class_section_tabs.tab(slug='notes', title='Notes', order=60,
                        template='cis/sections/tabs/_notes.html')
def notes_tab(request, record):
    from cis.models.note import ClassSectionNote
    notes = ClassSectionNote.objects.filter(class_section=record).order_by('-createdon')
    return {'notes': notes}


@class_section_tabs.tab(slug='change_history', title='Change History', order=200,
                        template='cis/sections/tabs/_change_history.html')
def change_history_tab(request, record):
    return {
        'history_table_id': 'class_section_history',
        'history_show_source_badge': False,
        'history_api_url': f'/ce/api/class-section-history/?class_section_id={record.id}',
    }
