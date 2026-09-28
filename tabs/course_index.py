"""Tabs on the CE courses index, `/ce/courses/` (package-cis #41).

An index page has no record, so this follows class_section_index_tabs:
the view calls `course_index_tabs.for_record(request, None, url_for)`. The
panes are rendered by cis/course/courses.html (and, for course_requirements
and course_administrators, by the instructor_app include it pulls in); the
registry decides which appear. Handlers return nothing because no pane is
fetched lazily.

Tenants opt out in their own myce/component_registry/course.py:

    from cis.tabs.course_index import course_index_tabs
    course_index_tabs.disable('course_administrators', 'app_requirements')
"""
from cis.tabs.registry import IndexTabRegistry

course_index_tabs = IndexTabRegistry()


def _pane(request, record):
    return {}


course_index_tabs.tab(slug='all', title='All Courses', order=10, active=True)(_pane)
# Hidden since before the registry: reachable only by #course_requirements.
course_index_tabs.tab(slug='course_requirements', title='Course Requirements',
                      order=20, hidden=True)(_pane)
course_index_tabs.tab(slug='course_administrators', title='By Course Administrator',
                      order=30)(_pane)
course_index_tabs.tab(slug='app_requirements', title='Teacher App Requirements',
                      order=40)(_pane)
course_index_tabs.tab(slug='document_requirements',
                      title='Course Document Requirements', order=50)(_pane)
