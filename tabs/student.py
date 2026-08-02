"""Student detail-page tab content functions.

Each function is registered with @student_tabs.tab(...) and returns a context
dict (rendered into the declared template) or an HttpResponse.  This module is
eager-imported by myce/component_registry/student.py so the decorators run.
"""
from myce.component_registry.student import student_tabs  # noqa: F401


# ---------------------------------------------------------------------------
# LAZY tabs (Task 2)
# ---------------------------------------------------------------------------

@student_tabs.tab(slug='details', title='Details', order=10,
                  template='cis/students/tabs/_details.html')
def details_tab(request, record):
    return {}


@student_tabs.tab(slug='ferpa', title='Information Release', order=20,
                  template='cis/students/tabs/_ferpa.html')
def ferpa_tab(request, record):
    return {'ferpa': record.get_ferpa()}


@student_tabs.tab(slug='recommendations', title='Recommendation(s)', order=40,
                  template='cis/students/tabs/_recommendations.html')
def recommendations_tab(request, record):
    from cis.services.table_configs import get_table_config
    build = get_table_config('student_recommendations_table').build_config
    return {'recommendations_table': build(
        variant='student_detail',
        api_url=f'/ce/api/student_recommendation?format=datatables&student={record.id}',
    )}


@student_tabs.tab(slug='agreements', title='Agreement(s)', order=50,
                  template='cis/students/tabs/_agreements.html')
def agreements_tab(request, record):
    from cis.models.term import Term
    from django.utils.safestring import mark_safe
    return {
        # mark_safe: the URL is rendered in a <script> string; without it Django
        # escapes & -> &amp;, mangling the ?student= filter (shows all students').
        'agreements_url': mark_safe(f'/ce/api/student_agreement?format=datatables&student={record.id}'),
        'terms': Term.objects.all(),
    }


@student_tabs.tab(slug='drop_wd', title='Drop Requests', order=80,
                  template='cis/students/tabs/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


# @student_tabs.tab(slug='parent_consents', title='Parent Consent for Home School', order=100,
#                   template='cis/students/tabs/_parent_consents.html')
def parent_consents_tab(request, record):
    from cis.models.term import Term
    from django.urls import reverse
    from django.utils.safestring import mark_safe
    return {
        # mark_safe: rendered in a <script> string — keep & unescaped so the
        # ?student= filter is sent intact (else all students' consents show).
        'parent_consents_url': mark_safe(f'/ce/api/parent_consent?format=datatables&student={record.id}'),
        'terms': Term.objects.all(),
        'student_ajax_url': reverse('cis:student_ajax'),
    }


# @student_tabs.tab(slug='transactions', title='Transactions', order=110,
#                   template='cis/students/tabs/_transactions.html')
def transactions_tab(request, record):
    from django.utils.safestring import mark_safe
    return {
        # mark_safe: rendered in a <script> string in the transactions include —
        # keep & unescaped so the ?student_id= filter is sent intact.
        'transactions_api_url': mark_safe(f'/ce/student_transactions/api/transactions/?format=datatables&student_id={record.id}'),
    }


@student_tabs.tab(slug='notes', title='Notes', order=120,
                  template='cis/students/tabs/_notes.html')
def notes_tab(request, record):
    from django.utils.safestring import mark_safe
    return {
        'note_api_url': mark_safe(f'/ce/api/student-note/?student_id={record.id}&format=datatables'),
    }


@student_tabs.tab(slug='change_history', title='Change History', order=130,
                  template='cis/students/tabs/_change_history.html')
def change_history_tab(request, record):
    return {
        'history_table_id': 'student_history',
        'history_show_source_badge': True,
        'history_api_url': f'/ce/api/student-history/?student_id={record.id}',
    }


# ---------------------------------------------------------------------------
# EAGER tabs (Task 3)
# ---------------------------------------------------------------------------

@student_tabs.tab(slug='classes', title='Course Requests', order=60, active=True, lazy=False,
                  template='cis/students/tabs/_classes.html')
def classes_tab(request, record):
    from cis.services.table_configs import get_table_config
    from cis.models import Term
    from django.urls import reverse
    build = get_table_config('registrations_table').build_config
    return {
        'registrations_table': build(
            variant='student_detail',
            api_url=f'/ce/api/registration?format=datatables&student={record.id}',
        ),
        'add_new_ajax_url': reverse('cis:add_new_ajax'),
        'register_for_class_url': reverse('cis:register_for_class', args=[record.id]),
        # The class lookup fragment (class_section_search.html) gates its UI on
        # these keys. Fragments don't inherit the parent page context, so set
        # them here to match the historic student-view context.
        'is_registration_open': True,
        'registration_terms': Term.objects.all(),
    }


@student_tabs.tab(slug='files', title='Supporting Documents', order=70, lazy=False,
                  template='cis/students/tabs/_files.html')
def files_tab(request, record):
    from cis.forms.student import StudentSupportingDocumentForm
    from cis.services.table_configs import get_table_config
    from myce.component_registry.support_docs import support_docs_actions
    from django.urls import reverse
    build = get_table_config('support_docs_table').build_config
    if request.method == 'POST' and request.POST.get('action') == 'upload_support_doc':
        form = StudentSupportingDocumentForm(record, data=request.POST, files=request.FILES)
        form.is_valid()
    else:
        form = StudentSupportingDocumentForm(record)
    return {
        'support_docs_table': build(
            variant='student_detail_ce',
            api_url=f'/ce/api/student_support_docs?format=datatables&student={record.id}',
            bulk_actions=support_docs_actions.for_scope('bulk', request.user),
            bulk_actions_url=reverse('cis:support_docs_bulk_actions'),
        ),
        'support_doc_form': form,
    }


# @student_tabs.tab(slug='campus_id', title='Campus ID(s)', order=90, lazy=False,
#                   template='cis/students/tabs/_campus_id.html')
def campus_id_tab(request, record):
    from cis.forms.student import StudentCampusIDForm
    from django.utils.safestring import mark_safe
    form = StudentCampusIDForm(initial={'id': '-1', 'student_id': record.id})
    return {
        'student_id_url': mark_safe(f'/ce/api/campus_id?format=datatables&student={record.id}'),
        'student_id_form': form,
    }


@student_tabs.tab(slug='migrate', title='Migrate Record', order=140, lazy=False,
                  template='cis/students/tabs/_migrate.html')
def migrate_tab(request, record):
    from cis.forms.student import MigrateStudentForm
    if request.method == 'POST' and request.POST.get('action') == 'migrate_student':
        form = MigrateStudentForm(request.POST)
        form.is_valid()
    else:
        form = MigrateStudentForm()
    return {'migration_form': form}
