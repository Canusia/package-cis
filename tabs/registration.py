"""Registration detail-page tab content functions.

Each function is registered with @registration_tabs.tab(...) and returns a
context dict (rendered into the declared template) or an HttpResponse.
Eager-imported by myce/component_registry/registration.py so decorators run.
"""
from myce.component_registry.registration import registration_tabs  # noqa: F401


@registration_tabs.tab(slug='classes', title='Classes', order=30,
                       template='cis/registrations/tabs/_classes.html')
def classes_tab(request, record):
    from cis.services.table_configs import get_table_config
    build = get_table_config('registrations_table').build_config
    return {'registrations_table': build(
        variant='registration_detail',
        api_url=f'/ce/api/registration?format=datatables&student={record.student.id}',
        current_record_id=str(record.id),
    )}


@registration_tabs.tab(slug='recommendation', title='Recommendation', order=50,
                       template='cis/registrations/tabs/_recommendation.html')
def recommendation_tab(request, record):
    return {'recommendation': record.get_recommendation()}


@registration_tabs.tab(slug='signatures', title='Agreement & Consent', order=60,
                       template='cis/registrations/tabs/_signatures.html')
def signatures_tab(request, record):
    return {
        'student_signature': record.get_student_signature(),
        'ferpa': record.student.get_ferpa(),
    }


@registration_tabs.tab(slug='notes', title='Notes', order=70,
                       template='cis/registrations/tabs/_notes.html')
def notes_tab(request, record):
    from django.utils.safestring import mark_safe
    return {'note_api_url': mark_safe(f'/ce/api/student-note/?student_id={record.student.id}&format=datatables')}


@registration_tabs.tab(slug='edit_registration', title='Edit Registration', order=10,
                       template='cis/registrations/tabs/_edit_registration.html',
                       lazy=False, active=True)
def edit_registration_tab(request, record):
    from cis.services.tenant_services import get_tenant_service
    EditStudentRegistration = get_tenant_service('registration_form').EditStudentRegistration
    from cis.utils import can_edit_campus_registration
    # detail() owns the save; rebind only to populate form.errors for re-display.
    if request.method == 'POST' and not request.POST.get('action'):
        # The main form has no hidden `action` field (pre-existing behaviour).
        # We rebind when action is absent (the registration update branch).
        if can_edit_campus_registration(request.user, record):
            form = EditStudentRegistration(record, request.POST)
            form.is_valid()
        else:
            form = EditStudentRegistration(record)
    else:
        form = EditStudentRegistration(record)
    return {'form': form}


@registration_tabs.tab(slug='student_details', title='Student Details', order=20,
                       template='cis/registrations/tabs/_student_details.html',
                       lazy=False, active=True)
def student_details_tab(request, record):
    return {}


@registration_tabs.tab(slug='campus_id', title='Campus ID(s)', order=40,
                       template='cis/registrations/tabs/_campus_id.html',
                       lazy=False)
def campus_id_tab(request, record):
    from django.utils.safestring import mark_safe
    from cis.forms.student import StudentCampusIDForm
    if request.method == 'POST' and request.POST.get('action') == 'edit_campus':
        student_id_form = StudentCampusIDForm(request.POST)
        student_id_form.is_valid()  # populate errors for re-display
    else:
        student_id_form = StudentCampusIDForm(
            initial={'id': '-1', 'student_id': record.student.id}
        )
    return {
        'student_id_url': mark_safe(f'/ce/api/campus_id?format=datatables&student={record.student.id}'),
        'student_id_form': student_id_form,
    }


@registration_tabs.tab(slug='change_history', title='Change History', order=200,
                       template='cis/registrations/tabs/_change_history.html')
def change_history_tab(request, record):
    return {
        'history_table_id': 'registration_history',
        'history_show_source_badge': False,
        'history_api_url': f'/ce/api/registration-history/?registration_id={record.id}',
    }
