"""Academic Year detail-page tab content functions (see cis/tabs/course.py).
Eager-imported by myce/component_registry/academic_year.py so decorators run.
"""
from myce.component_registry.academic_year import academic_year_tabs  # noqa: F401


def _ay_reg_summary_url(record):
    return f'/ce/api/registration-summary/?academic_year_id={record.id}&format=datatables'


@academic_year_tabs.tab(slug='terms', title='Terms', order=20,
                        template='cis/term/tabs/academic_year/_terms.html', active=True)
def terms_tab(request, record):
    from cis.services.table_configs import get_table_config
    return {'terms_table': get_table_config('terms_table').build_config(
        variant='academic_year_terms',
        api_url=f'/ce/api/term?academic_year={record.id}&format=datatables',
        details_prefix='/ce/term/',
    )}


@academic_year_tabs.tab(slug='class_sections', title='Offerings By Course', order=30,
                        template='cis/term/tabs/academic_year/_class_sections.html')
def class_sections_tab(request, record):
    from cis.services.table_configs import get_table_config
    return {'sections_table': get_table_config('sections_table').build_config(
        variant='academic_year_detail',
        api_url=f'/ce/api/class_section/?academic_year_id={record.id}&format=datatables&term=-1',
    )}


@academic_year_tabs.tab(slug='registrations_summary', title='Registrations By Course', order=40,
                        template='cis/term/tabs/academic_year/_registrations_summary.html')
def registrations_summary_tab(request, record):
    return {'registration_summary_api_url': _ay_reg_summary_url(record)}


@academic_year_tabs.tab(slug='students_summary', title='Students By High School', order=50,
                        template='cis/term/tabs/academic_year/_students_summary.html')
def students_summary_tab(request, record):
    return {'registration_summary_api_url': _ay_reg_summary_url(record)}


@academic_year_tabs.tab(slug='registration_hs_summary', title='Registrations By High School', order=60,
                        template='cis/term/tabs/academic_year/_registration_hs_summary.html')
def registration_hs_summary_tab(request, record):
    return {'registration_summary_api_url': _ay_reg_summary_url(record)}


@academic_year_tabs.tab(slug='visits', title='Visit(s)', order=70,
                        template='cis/term/tabs/academic_year/_visits.html')
def visits_tab(request, record):
    return {}


@academic_year_tabs.tab(slug='drop_wd', title='Drop Requests', order=80,
                        template='cis/term/tabs/academic_year/_drop_wd.html')
def drop_wd_tab(request, record):
    return {}


@academic_year_tabs.tab(slug='details', title='Details', order=10,
                        template='cis/term/tabs/academic_year/_details.html', lazy=False)
def details_tab(request, record):
    from cis.forms.term import AcademicYearForm
    if request.method == 'POST' and request.POST.get('action') != 'migrate_academic_year':
        form = AcademicYearForm(request.POST, instance=record)
        form.is_valid()
    else:
        form = AcademicYearForm(instance=record)
    return {'form': form, 'record': record}


@academic_year_tabs.tab(slug='migrate', title='Migrate Record', order=90,
                        template='cis/term/tabs/academic_year/_migrate.html', lazy=False)
def migrate_tab(request, record):
    from cis.forms.term import MigrateAcademicYearForm
    if request.method == 'POST' and request.POST.get('action') == 'migrate_academic_year':
        form = MigrateAcademicYearForm(record=record, data=request.POST)
        form.is_valid()
    else:
        form = MigrateAcademicYearForm(record=record)
    return {'migration_form': form}
