"""Course types: the high school Course Types tab's approval actions and the
/ce/course-types/ master page.

Approval actions follow the Campuses tab (views/highschool.py
highschool_campus_*): two-step ActionRegistry posts. A user may act on an
approval when ``can_manage_link`` allows its campus; an all-campus approval
(campus None) is therefore superuser-only in multi-campus mode.
"""
from django.db.models import Count
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.urls import reverse

from cis.campus_context import scope_to_current_campus
from cis.forms.course_type import (
    CourseTypeForm, HighSchoolCourseTypeAddForm, HighSchoolCourseTypeEditForm)
from cis.highschool_scope import can_manage_link, scope_highschools
from cis.menu import cis_menu, draw_menu
from cis.models.course_type import CourseType, HighSchoolCourseType
from cis.models.highschool import HighSchool
from cis.models.section import ClassSection
from cis.settings.course_type_gate import course_type_gate
from cis.utils import user_has_cis_role
from cis.views.highschool import _forbidden, _form_error

# Terms shown in the master page's "college sections with no course type" panel.
UNCLASSIFIED_TERMS_SHOWN = 4


def _links_done(title, message):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'reloadHighschoolCourseTypes',
        'args': {'title': title, 'message': message},
    })


def _modal(template, context, request):
    return JsonResponse({
        'outcome': 'modal',
        'html': render_to_string(template, context, request=request),
    })


def highschool_course_type_add(request, record_id):
    """Approve one or more course types for a high school."""
    if not user_has_cis_role(request.user):
        return _forbidden()
    record = get_object_or_404(
        scope_highschools(HighSchool.objects.all(), user=request.user), pk=record_id)
    action_url = str(reverse('cis:highschool_course_type_add', args=[record.id]))
    form_kwargs = {
        'user': request.user, 'highschool': record,
        'allow_create': course_type_gate.allow_create_from_tab(),
    }

    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/course_type_link_form.html', {
            'title': 'Approve Course Types',
            'form': HighSchoolCourseTypeAddForm(**form_kwargs),
            'form_action': action_url, 'submit_label': 'Approve', 'record': record,
        }, request)

    form = HighSchoolCourseTypeAddForm(request.POST, **form_kwargs)
    if not form.is_valid():
        return _form_error(form)
    links = form.save_or_error()
    if links is None:
        return _form_error(form)
    return _links_done(
        'Course types approved',
        'Approved %s for %s.' % (', '.join(link.course_type.name for link in links),
                                 record.name))


def _get_manageable_link(request, link_id):
    """(link, None) when the user may act on it, else (None, response)."""
    if not user_has_cis_role(request.user):
        return None, _forbidden()
    link = get_object_or_404(
        HighSchoolCourseType.objects.select_related('highschool', 'course_type', 'campus'),
        pk=link_id,
        highschool__in=scope_highschools(HighSchool.objects.all(), user=request.user))
    if not can_manage_link(request.user, link.campus):
        return None, _forbidden()
    return link, None


def highschool_course_type_edit(request, link_id):
    """Edit an approval's status (and campus, in multi-campus mode)."""
    link, denied = _get_manageable_link(request, link_id)
    if denied:
        return denied
    action_url = str(reverse('cis:highschool_course_type_edit', args=[link.id]))

    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/course_type_link_form.html', {
            'title': 'Edit Course Type Approval',
            'form': HighSchoolCourseTypeEditForm(instance=link, user=request.user),
            'form_action': action_url, 'submit_label': 'Save',
            'record': link.highschool, 'link': link,
        }, request)

    form = HighSchoolCourseTypeEditForm(request.POST, instance=link, user=request.user)
    if not form.is_valid():
        return _form_error(form)
    if form.save_or_error() is None:
        return _form_error(form)
    return _links_done(
        'Approval updated',
        'Updated %s for %s.' % (link.course_type.name, link.highschool.name))


def highschool_course_type_delete(request, link_id):
    """Remove an approval (confirmation modal, then delete)."""
    link, denied = _get_manageable_link(request, link_id)
    if denied:
        return denied

    if request.POST.get('apply') != '1':
        return _modal('cis/highschools/course_type_link_delete.html', {
            'title': 'Remove Course Type Approval', 'link': link,
            'form_action': str(reverse('cis:highschool_course_type_delete', args=[link.id])),
        }, request)

    type_name, highschool_name = link.course_type.name, link.highschool.name
    link.delete()
    return _links_done(
        'Approval removed', 'Removed %s from %s.' % (type_name, highschool_name))


# -- /ce/course-types/ master page ---------------------------------------------

def _course_types_done(title, message):
    return JsonResponse({
        'outcome': 'call',
        'fn': 'reloadCourseTypes',
        'args': {'title': title, 'message': message},
    })


def _unclassified_by_term():
    """College sections (no high school) with no course type, per recent term.

    So CE can classify them before turning the course-type gate on: an
    unclassified college section is hidden while the gate is on.
    """
    sections = scope_to_current_campus(
        ClassSection.objects.filter(highschool__isnull=True, course_type__isnull=True),
        'course__campus')
    rows = (sections.values('term__id', 'term__code', 'term__label')
            .annotate(count=Count('id')).order_by('-term__code'))
    return list(rows[:UNCLASSIFIED_TERMS_SHOWN])


def index(request):
    """All course types with approval and section counts."""
    if not user_has_cis_role(request.user):
        return _forbidden()
    records = CourseType.objects.annotate(
        school_count=Count('highschool_links__highschool', distinct=True),
        section_count=Count('class_sections', distinct=True),
    ).order_by('sort_order', 'name')
    return render(request, 'cis/course_types/index.html', {
        'page_title': 'Course Types',
        'records': records,
        'gate': course_type_gate.get_config(),
        'unclassified': _unclassified_by_term(),
        'menu': draw_menu(cis_menu, 'highschools', 'course_types'),
    })


def _course_type_form_view(request, record=None):
    if record is None:
        action_url, title, label = str(reverse('cis:course_type_add')), 'Add Course Type', 'Add'
    else:
        action_url = str(reverse('cis:course_type_edit', args=[record.id]))
        title, label = 'Edit Course Type', 'Save'

    if request.POST.get('apply') != '1':
        return _modal('cis/course_types/form.html', {
            'title': title, 'form': CourseTypeForm(instance=record),
            'form_action': action_url, 'submit_label': label,
        }, request)

    form = CourseTypeForm(request.POST, instance=record)
    if not form.is_valid():
        return _form_error(form)
    saved = form.save()
    return _course_types_done('Course type saved', 'Saved %s.' % saved.name)


def course_type_add(request):
    if not user_has_cis_role(request.user):
        return _forbidden()
    return _course_type_form_view(request)


def course_type_edit(request, record_id):
    if not user_has_cis_role(request.user):
        return _forbidden()
    return _course_type_form_view(request, get_object_or_404(CourseType, pk=record_id))
