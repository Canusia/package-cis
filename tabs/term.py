"""Term detail-page tab content functions (see cis/tabs/course.py for the pattern).
Eager-imported by myce/component_registry/term.py so decorators run.
"""
from django.shortcuts import get_object_or_404  # noqa: F401  (used by later tabs)

from myce.component_registry.term import term_tabs  # noqa: F401


def _sections_build(variant, record):
    from cis.services.table_configs import get_table_config
    return get_table_config('sections_table').build_config(
        variant=variant,
        api_url=f'/ce/api/class_section/?term={record.id}&format=datatables',
    )


@term_tabs.tab(slug='class_sections', title='Offerings By Course', order=20,
               template='cis/term/tabs/_class_sections.html', active=True)
def class_sections_tab(request, record):
    return {'sections_table_by_course': _sections_build('term_detail_by_course', record)}


@term_tabs.tab(slug='class_sections_by_hs', title='Offerings By High School', order=30,
               template='cis/term/tabs/_class_sections_by_hs.html')
def class_sections_by_hs_tab(request, record):
    return {'sections_table_by_hs': _sections_build('term_detail_by_hs', record)}


def _term_reg_summary_url(record):
    return f'/ce/api/registration-summary/?term_id={record.id}&format=datatables'


@term_tabs.tab(slug='registrations_summary', title='Registrations Summary', order=40,
               template='cis/term/tabs/_registrations_summary.html')
def registrations_summary_tab(request, record):
    return {'registration_summary_api_url': _term_reg_summary_url(record)}


@term_tabs.tab(slug='students_summary', title='Students By High School', order=50,
               template='cis/term/tabs/_students_summary.html')
def students_summary_tab(request, record):
    return {'registration_summary_api_url': _term_reg_summary_url(record)}


@term_tabs.tab(slug='registration_hs_summary', title='Registrations By High School', order=60,
               template='cis/term/tabs/_registration_hs_summary.html')
def registration_hs_summary_tab(request, record):
    return {'registration_summary_api_url': _term_reg_summary_url(record)}


@term_tabs.tab(slug='visits', title='Visit(s)', order=70,
               template='cis/term/tabs/_visits.html')
def visits_tab(request, record):
    return {}


@term_tabs.tab(slug='drop_wd', title='Drop Requests', order=80,
               template='cis/term/tabs/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


@term_tabs.tab(slug='details', title='Details', order=10,
               template='cis/term/tabs/_details.html', lazy=False)
def details_tab(request, record):
    from cis.forms.term import TermForm
    # detail() saves the main form in its non-migrate POST branch; rebind to show errors.
    if request.method == 'POST' and request.POST.get('action') != 'migrate_term':
        form = TermForm(request.POST, instance=record)
        form.is_valid()
    else:
        form = TermForm(instance=record)
    return {'form': form, 'record': record}


@term_tabs.tab(slug='migrate', title='Migrate Record', order=90,
               template='cis/term/tabs/_migrate.html', lazy=False)
def migrate_tab(request, record):
    from cis.forms.term import MigrateTermForm
    if request.method == 'POST' and request.POST.get('action') == 'migrate_term':
        form = MigrateTermForm(record=record, data=request.POST)
        form.is_valid()
    else:
        form = MigrateTermForm(record=record)
    return {'migration_form': form}
