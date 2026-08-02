"""FacultyCoordinator detail-page tab content functions (see cis/tabs/course.py).
Eager-imported by myce/component_registry/faculty_coordinator.py so decorators run.
"""
from django.utils.safestring import mark_safe

from myce.component_registry.faculty_coordinator import faculty_coordinator_tabs  # noqa: F401


@faculty_coordinator_tabs.tab(slug='courses', title='Course(s)', order=10,
                              template='cis/faculty/tabs/_courses.html',
                              active=True)
def courses_tab(request, record):
    # mark_safe: this URL carries a '&' and is interpolated into a JS string
    # literal in the fragment. Without it Django emits '&amp;', which browsers
    # do NOT decode inside JS strings, so the filter param would be lost and
    # the table would list every CourseAdministrator row.
    return {'course_administrator_url': mark_safe(
        '/ce/api/course_administrator?format=datatables'
        f'&faculty_coordinator_user_id={record.user.id}')}


@faculty_coordinator_tabs.tab(slug='class_sections', title='Class Sections',
                              order=20,
                              template='cis/faculty/tabs/_class_sections.html')
def class_sections_tab(request, record):
    from cis.models.term import Term
    from cis.services.table_configs import get_table_config

    build = get_table_config('sections_table').build_config
    # No mark_safe needed: this URL is consumed via the table config's
    # opts_json|safe, not interpolated into a JS string by the fragment.
    api_url = (
        f'/ce/api/class_section/?course_administrator_user_id={record.user.id}'
        '&term=-1&format=datatables')
    return {
        'sections_table': build(
            variant='faculty_coordinator_detail',
            api_url=api_url,
            filter_form_selector='#fc_class_section_filter',
        ),
        # Opens on "All Terms" (term=-1), matching EWU's sibling sections tabs
        # (cis/tabs/highschool.py, course.py, teacher.py). The user narrows via
        # the dropdown.
        'terms': Term.objects.all().order_by('-code'),
    }


@faculty_coordinator_tabs.tab(slug='visits', title='Visit(s)', order=30,
                              template='cis/faculty/tabs/_visits.html')
def visits_tab(request, record):
    return {}
