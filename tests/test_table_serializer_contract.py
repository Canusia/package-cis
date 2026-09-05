"""Every path a CE DataTable reads must survive its serializer (issue #67).

drf-datatables trims unused fields in ``DatatablesRenderer._filter_unused_fields()``,
but only at the top level: a nested serializer is kept whole or dropped whole.
So /ce/registrations/ renders 11 columns and ships 917 JSON keys and 30 KB per
row, because everything it renders lives under class_section, student or term.

Narrowing those serializers breaks a table by *omission*, and the failure is
silent -- DataTables renders a blank cell for a missing ``data-data`` path, and
a render callback that reads an absent field draws nothing rather than raising.
Nothing else in the suite would catch it.

These tests read the table's own two registries -- the ``data-data`` attributes
in its column-header HTML under ``myce_tenant_configs/services/``, and the
``row.<path>`` references in its ``*_table.js`` -- and assert the feed still
answers every one of them. Columns alone are not enough: registrations_table.js
reads 32 paths for an 11-column table, and students_table.js reads
current_state_balance and current_student_balance, which are not columns at all.
"""

import importlib
import json
import os
import re
import uuid

from django.conf import settings
from django.contrib.auth.models import Group
from django.test import TestCase

from cis.models import CustomUser
from cis.urls import router_viewsets

_MISSING = object()

# Method names that a `row.<path>` grep picks up but which are JS calls, not
# fields: `row.co_reqs.forEach(...)` means the table needs co_reqs, not
# co_reqs.forEach.
_JS_METHODS = {
    'forEach', 'length', 'map', 'join', 'push', 'trim', 'split',
    'toLowerCase', 'toUpperCase', 'replace', 'filter', 'indexOf', 'slice',
    'includes', 'toString', 'concat', 'find', 'some', 'every', 'sort',
}

_JS_DIR = os.path.join(
    settings.BASE_DIR if hasattr(settings, 'BASE_DIR') else '',
    'myce_tenant_configs', 'staticfiles', 'js')


def _service(module_name):
    return importlib.import_module(
        f'myce_tenant_configs.services.{module_name}')


def _registries(module_name):
    """(profiles, column-header-HTML) out of a table-config service module.

    The services do not share variable names -- COLUMN_HEADER_HTML in one,
    _COLUMNS in another -- so the dicts are identified by shape: the profiles
    dict maps names to dicts with a 'columns' key, the header dict maps names
    to '<th ...>' strings.
    """
    profiles = header = None
    for value in vars(_service(module_name)).values():
        if not isinstance(value, dict) or not value:
            continue
        values = list(value.values())
        if all(isinstance(v, dict) and 'columns' in v for v in values):
            profiles = value
        elif (header is None
              and all(isinstance(v, str) and v.lstrip().startswith('<th')
                      for v in values)):
            header = value
    return profiles, header


def _columns(module_name, variant):
    profiles, header = _registries(module_name)
    out = []
    for key in profiles[variant]['columns']:
        match = re.search(r'data-data="([^"]+)"', header[key])
        if match:
            out.append(match.group(1))
    return out


def _js_paths(js_name):
    path = os.path.join(_JS_DIR, js_name + '.js')
    if not os.path.exists(path):
        return set()
    with open(path) as handle:
        source = handle.read()
    found = set()
    for raw in re.findall(r'\brow\.([A-Za-z_][A-Za-z0-9_.]*)', source):
        parts = [p for p in raw.split('.') if p not in _JS_METHODS]
        if parts:
            found.add('.'.join(parts))
    return found


def paths_for(module_name, variant, js_name):
    """(columns, every leaf path this table reads).

    A bare object path (``row.highschool``) sitting next to a deeper one
    (``row.highschool.name``) is a truthiness check, not a field requirement,
    so it is pruned -- otherwise the contract would demand the whole nested
    object and there would be nothing left to narrow.
    """
    columns = _columns(module_name, variant)
    raw = set(columns) | _js_paths(js_name)
    leaves = {p for p in raw
              if not any(o != p and o.startswith(p + '.') for o in raw)}
    return columns, leaves


def dig(row, path):
    """The value at a dotted path, or _MISSING.

    A present-but-null FK is fine; an absent key is the bug. `None` cannot
    distinguish the two, hence the sentinel.
    """
    current = row
    for part in path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


# (label, service module, profile variant, *_table.js name, feed basename,
#  extra GET params)
#
# `class_section` and `registration` default to the active term, which no
# fixture row belongs to, so they are widened: term=-1 means "all" for the
# section feed and term=-3 for the registration feed. `class-registered` needs
# a campus_id or its UUID guard short-circuits to none().
TABLE_CONTRACTS = (
    ('/ce/students/', 'students_table', 'students_index',
     'students_table', 'student', {}),
    ('/ce/students/support_docs/', 'support_docs_table', 'support_docs_index',
     'support_docs_table', 'student_support_docs', {}),
    ('/ce/registrations/', 'registrations_table', 'registration_index',
     'registrations_table', 'registration', {'term': '-3'}),
    ('/ce/students/notes/', 'student_notes_table', 'student_notes_index',
     'student_notes_table', 'student-note', {}),
    ('/ce/highschools/', 'highschools_table', 'highschools_active',
     'highschools_table', 'highschool', {}),
    ('/ce/highschool_admins/', 'hs_admins_table', 'hs_admins_index',
     'hs_admins_table', 'hs-administrator-position', {}),
    ('/ce/highschool_admin/access_requests', 'access_requests_table',
     'access_requests_index', 'access_requests_table',
     'hs-administrator-access-request', {}),
    ('/ce/sections/', 'sections_table', 'sections_index',
     'sections_table', 'class_section', {'term': '-1'}),
    ('/ce/courses/', 'courses_table', 'courses_index',
     'courses_table', 'course', {}),
    ('/ce/instructors/', 'instructors_table', 'instructors_index',
     'instructors_table', 'teacher', {}),
    ('/ce/faculty_coordinators/', 'faculty_coords_table',
     'faculty_coords_index', 'faculty_coords_table', 'course_administrator', {}),
    ('highschool detail > instructors', 'instructors_table',
     'highschool_instructors', 'instructors_table', 'highschool-teacher', {}),
    ('course detail > instructors', 'instructors_table', 'course_instructors',
     'instructors_table', 'teacher-course', {}),
    ('course detail > offerings', 'sections_table', 'course_detail',
     'sections_table', 'class_section', {'term': '-1'}),
    ('course detail > administrators', 'faculty_coords_table',
     'faculty_coords_detail', 'faculty_coords_table',
     'course_administrator', {}),
    ('section detail > students', 'registrations_table', 'section_detail',
     'registrations_table', 'registration', {'term': '-3'}),
    ('student detail > classes', 'registrations_table', 'student_detail',
     'registrations_table', 'registration', {'term': '-3'}),
    ('student detail > files', 'support_docs_table', 'student_detail_ce',
     'support_docs_table', 'student_support_docs', {}),
    # One narrowed serializer serves every profile of a feed, so every profile
    # has to be here -- not just the ones the index pages use. These seven were
    # missed on the first pass and cost a regression: hs_admin_roles renders
    # `since`, which the narrowed serializer had dropped. Filters are left off
    # deliberately; the question a contract asks is whether the serializer
    # answers the profile's paths, not whether the viewset's filter matches.
    ('academic year detail > sections', 'sections_table',
     'academic_year_detail', 'sections_table', 'class_section', {'term': '-1'}),
    ('highschool detail > sections (profile)', 'sections_table',
     'highschool_detail', 'sections_table', 'class_section', {'term': '-1'}),
    ('instructor detail > sections (profile)', 'sections_table',
     'instructor_detail', 'sections_table', 'class_section', {'term': '-1'}),
    ('hs admin detail > roles', 'hs_admins_table', 'hs_admin_roles',
     'hs_admins_table', 'hs-administrator-position', {}),
    ('/ce/students/ dirty', 'students_table', 'dirty_index',
     'students_table', 'student', {}),
    ('/ce/students/ missing recommendation', 'students_table',
     'missing_recommendation_index', 'students_table', 'student', {}),
    ('cohort detail > instructors', 'instructors_table', 'cohort_instructors',
     'instructors_table', 'teacher-course', {}),
    # The last profiles on a trimmed feed. registration_detail is the one
    # package-cis#11 was filed for: it renders a `pay_type` column that the
    # v0.0.26 enumeration dropped, and it was not under contract -- which is
    # exactly why nothing here caught it.
    ('registration detail > tab', 'registrations_table', 'registration_detail',
     'registrations_table', 'registration', {'term': '-3'}),
    ('hs student detail > registrations', 'registrations_table',
     'hs_student_detail', 'registrations_table', 'registration', {'term': '-3'}),
    ('faculty coordinator detail > sections', 'sections_table',
     'faculty_coordinator_detail', 'sections_table', 'class_section',
     {'term': '-1'}),
    ('term detail > sections by course', 'sections_table',
     'term_detail_by_course', 'sections_table', 'class_section', {'term': '-1'}),
    ('term detail > sections by highschool', 'sections_table',
     'term_detail_by_hs', 'sections_table', 'class_section', {'term': '-1'}),
    ('student detail > files (student profile)', 'support_docs_table',
     'student_detail', 'support_docs_table', 'student_support_docs', {}),
)

# Bytes per row each feed may ship: measured against this fixture, plus
# headroom. `before` is the same measurement against the untrimmed
# serializers, so the pair shows what the four dropped aggregates were costing
# -- large where they dominate (the section, registration and instructor
# feeds), nil where the bulk is nested scalars the trimmed serializers keep on
# purpose. Three budgets sit *above* their before-figure, which is the honest
# signal that trimming buys nothing on those feeds: the price of not
# enumerating fields, and the right price.
#
#                                     feed   budget   before
PAYLOAD_BUDGETS = {
    'registration':                         8080,  # 14424
    'class_section':                        4090,  # 10798
    'teacher-course':                       2730,  # 5719
    'highschool-teacher':                    780,  # 5042
    'course_administrator':                 1800,  # 4354
    'student_support_docs':                 2940,  # 2636
    'student-note':                         2730,  # 2457
    'student':                              1280,  # 1192
    'hs-administrator-position':            1280,  # 1180
    'hs-administrator-access-request':       750,  # 732
    'teacher':                               660,  # 571
    'course':                                500,  # 512
    'highschool':                            340,  # 289
}



class TableContractFixture:
    """One row for every feed under contract."""

    @staticmethod
    def build():
        from cis.models.highschool_administrator import (
            HSAdministratorAccessRequest)
        from cis.models.student import StudentSupportingDocument
        from cis.tests.test_datatable_feed_query_counts import FeedFixture

        registration = FeedFixture.build()
        highschool = registration.class_section.highschool
        HSAdministratorAccessRequest.objects.create(
            name='Ada Requester', email='ada@example.com', phone='555-0100',
            highschool=highschool, role='Counselor', status='Pending')
        # FeedFixture creates one already; this is the /ce/ variant's row.
        StudentSupportingDocument.objects.filter(
            student=registration.student).update(status='Received')
        return registration


def render_feed(basename, columns, extra, user, length=20):
    """(rows, response) for a real datatables request to `basename`.

    force_authenticate rather than Client.force_login: the
    django_login_history post-login receiver calls ipaddress.ip_address(None)
    under the test client and raises ValueError.
    """
    from rest_framework.test import APIRequestFactory, force_authenticate

    params = {'format': 'datatables', 'draw': '1', 'start': '0',
              'length': str(length), 'search[value]': '',
              'order[0][column]': '0', 'order[0][dir]': 'asc', **extra}
    for index, column in enumerate(columns):
        params[f'columns[{index}][data]'] = column
        params[f'columns[{index}][name]'] = column
        params[f'columns[{index}][searchable]'] = 'true'
        params[f'columns[{index}][orderable]'] = 'true'
        params[f'columns[{index}][search][value]'] = ''

    request = APIRequestFactory().get('/x', params)
    force_authenticate(request, user=user)
    response = router_viewsets[basename].as_view({'get': 'list'})(request)
    response.render()
    return json.loads(response.content).get('data', []), response


# The contract: every path each table's registries name that its feed answers.
#
# Frozen as data rather than derived at assert time -- deriving it live would
# make it self-fulfilling, and the derivation is untrustworthy on its own,
# because one *_table.js serves several profiles across several feeds and a
# row.<path> grep attributes one profile's fields to another.
# test_the_registries_still_say_what_the_contract_was_built_from re-derives and
# compares, so a new column or callback fails there first.
#
# All 31 profiles that read a trimmed feed are covered. Under the v0.0.26
# design, where the serializers enumerated their fields, a profile left out of
# this list meant a silently blank column -- that cost profile_dirty_at,
# `since` and pay_type (package-cis#11). The serializers subclass their
# originals now and give up only four aggregates, so an unlisted profile can
# only break by naming a path *inside* one of those. The coverage stays
# because it is what demonstrates that.
FROZEN_PATHS = {
    '/ce/students/': [
        'account_verified', 'application_status',
        'application_status_display', 'ce_url', 'graduation_date',
        'highschool.name', 'id', 'parent_email', 'sis_sent_on',
        'user.created_at', 'user.email', 'user.first_name',
        'user.last_name', 'user.psid',
    ],
    '/ce/students/support_docs/': [
        'description', 'document_type', 'id', 'media', 'status',
        'student.ce_url', 'student.user.first_name',
        'student.user.last_name', 'term.label', 'uploaded_on',
    ],
    '/ce/registrations/': [
        'ce_url', 'changed_on', 'class_section.class_number',
        'class_section.course.catalog_number',
        'class_section.course.cohort.designator',
        'class_section.course.credit_hours',
        'class_section.course.name', 'class_section.course.title',
        'class_section.highschool.name',
        'class_section.highschool_course_name',
        'class_section.prereq', 'class_section.section_number',
        'class_section.term.code', 'class_section.term.label',
        'created_on', 'grade', 'has_recommendation',
        'has_signed_parent_consent', 'has_signed_student_agreement',
        'id', 'needs_mirroring', 'needs_recommendation',
        'pay_type_pretty', 'reviewed_on', 'status', 'status_pretty',
        'student.grade_level', 'student.highschool.name',
        'student.user.first_name', 'student.user.last_name',
        'student.user.psid', 'submitted_grade',
    ],
    '/ce/students/notes/': [
        'createdby.first_name', 'createdby.last_name', 'createdon',
        'id', 'media', 'meta.type', 'note', 'student.ce_url',
        'student.highschool.name', 'student.user.first_name',
        'student.user.last_name',
    ],
    '/ce/highschools/': [
        'address1', 'city', 'code', 'hs_pay_type',
        'hs_type_display', 'id', 'name', 'postal_code',
        'primary_phone', 'sau', 'state', 'status',
    ],
    '/ce/highschool_admins/': [
        'highschool.name', 'hsadmin.id', 'hsadmin.user.email',
        'hsadmin.user.first_name', 'hsadmin.user.last_login',
        'hsadmin.user.last_name', 'hsadmin.user.primary_phone',
        'id', 'position.name', 'status',
    ],
    '/ce/highschool_admin/access_requests': [
        'email', 'highschool.name', 'id', 'name', 'status',
        'submittedon',
    ],
    '/ce/sections/': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'num_students', 'registered_students',
        'registration_term.label', 'roster_status',
        'section_number', 'status', 'teacher.user.first_name',
        'teacher.user.last_name', 'term.code', 'term.label',
    ],
    '/ce/courses/': [
        'campus.name', 'credit_hours', 'id', 'is_available_for_si',
        'name', 'status', 'title',
    ],
    '/ce/instructors/': [
        'id', 'status', 'user.email', 'user.first_name',
        'user.last_login', 'user.last_name', 'user.primary_phone',
    ],
    '/ce/faculty_coordinators/': [
        'course.name', 'faculty_id', 'id', 'role', 'status',
        'user.email', 'user.first_name', 'user.last_login',
        'user.last_name',
    ],
    'highschool detail > instructors': [
        'status', 'teacher.ce_url', 'teacher.user.email',
        'teacher.user.first_name', 'teacher.user.last_name',
    ],
    'course detail > instructors': [
        'id', 'status', 'teacher_highschool.highschool.name',
        'teacher_highschool.teacher.user.last_name',
    ],
    'course detail > offerings': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number',
        'teacher.user.first_name', 'teacher.user.last_name',
        'term.code', 'term.label',
    ],
    'course detail > administrators': [
        'course.name', 'faculty_id', 'id', 'role', 'status',
    ],
    'section detail > students': [
        'ce_url', 'changed_on', 'class_section.class_number',
        'class_section.course.catalog_number',
        'class_section.course.cohort.designator',
        'class_section.course.credit_hours',
        'class_section.course.name', 'class_section.course.title',
        'class_section.highschool.name',
        'class_section.highschool_course_name',
        'class_section.prereq', 'class_section.section_number',
        'class_section.term.label', 'created_on', 'grade',
        'has_recommendation', 'has_signed_parent_consent',
        'has_signed_student_agreement', 'id', 'needs_mirroring',
        'needs_recommendation', 'pay_type_pretty', 'reviewed_on',
        'status', 'status_pretty', 'student.highschool.name',
        'student.user.first_name', 'student.user.last_name',
        'student.user.psid', 'submitted_grade',
    ],
    'student detail > classes': [
        'ce_url', 'changed_on', 'class_section.class_number',
        'class_section.course.catalog_number',
        'class_section.course.cohort.designator',
        'class_section.course.credit_hours',
        'class_section.course.name', 'class_section.course.title',
        'class_section.highschool.name',
        'class_section.highschool_course_name',
        'class_section.prereq', 'class_section.section_number',
        'class_section.term.code', 'class_section.term.label',
        'created_on', 'grade', 'has_recommendation',
        'has_signed_parent_consent', 'has_signed_student_agreement',
        'id', 'needs_mirroring', 'needs_recommendation',
        'pay_type_pretty', 'reviewed_on', 'status', 'status_pretty',
        'student.highschool.name', 'student.user.first_name',
        'student.user.last_name', 'student.user.psid',
        'submitted_grade',
    ],
    'student detail > files': [
        'description', 'document_type', 'id', 'media', 'status',
        'term.label', 'uploaded_on',
    ],
    'academic year detail > sections': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number', 'status',
        'teacher.user.first_name', 'teacher.user.last_name',
        'term.code', 'term.label',
    ],
    'highschool detail > sections (profile)': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number',
        'teacher.user.first_name', 'teacher.user.last_name',
        'term.code', 'term.label',
    ],
    'instructor detail > sections (profile)': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number',
        'teacher.user.first_name', 'teacher.user.last_name',
        'term.code', 'term.label',
    ],
    'hs admin detail > roles': [
        'highschool.name', 'hsadmin.id', 'hsadmin.user.email',
        'hsadmin.user.first_name', 'hsadmin.user.last_name',
        'hsadmin.user.primary_phone', 'id', 'position.name',
        'since', 'status',
    ],
    '/ce/students/ dirty': [
        'application_status', 'application_status_display',
        'ce_url', 'highschool.name', 'id', 'parent_email',
        'profile_dirty_at', 'sis_sent_on', 'user.email',
        'user.first_name', 'user.last_name',
    ],
    '/ce/students/ missing recommendation': [
        'application_status', 'application_status_display',
        'ce_url', 'highschool.name', 'id', 'parent_email',
        'sis_sent_on', 'user.email', 'user.first_name',
        'user.last_name',
    ],
    'cohort detail > instructors': [
        'course.name', 'id', 'status',
        'teacher_highschool.highschool.name',
        'teacher_highschool.teacher.user.last_name',
    ],
    'registration detail > tab': [
        'ce_url', 'changed_on', 'class_section.class_number',
        'class_section.course.catalog_number',
        'class_section.course.cohort.designator',
        'class_section.course.credit_hours',
        'class_section.course.name', 'class_section.course.title',
        'class_section.highschool.name',
        'class_section.highschool_course_name',
        'class_section.prereq', 'class_section.section_number',
        'class_section.term.code', 'class_section.term.label',
        'created_on', 'grade', 'has_recommendation',
        'has_signed_parent_consent', 'has_signed_student_agreement',
        'id', 'needs_mirroring', 'needs_recommendation', 'pay_type',
        'pay_type_pretty', 'reviewed_on', 'status', 'status_pretty',
        'student.highschool.name', 'student.user.first_name',
        'student.user.last_name', 'student.user.psid',
        'submitted_grade',
    ],
    'hs student detail > registrations': [
        'changed_on', 'class_section.class_number',
        'class_section.course.catalog_number',
        'class_section.course.cohort.designator',
        'class_section.course.credit_hours',
        'class_section.course.name', 'class_section.course.title',
        'class_section.highschool.name',
        'class_section.highschool_course_name',
        'class_section.prereq', 'class_section.section_number',
        'class_section.term.code', 'class_section.term.label',
        'created_on', 'grade', 'has_recommendation',
        'has_signed_parent_consent', 'has_signed_student_agreement',
        'id', 'needs_mirroring', 'needs_recommendation',
        'pay_type_pretty', 'reviewed_on', 'status', 'status_pretty',
        'student.highschool.name', 'student.user.first_name',
        'student.user.last_name', 'student.user.psid',
        'submitted_grade',
    ],
    'faculty coordinator detail > sections': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number',
        'teacher.user.first_name', 'teacher.user.last_name',
        'term.code', 'term.label',
    ],
    'term detail > sections by course': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number', 'status',
        'teacher.user.first_name', 'teacher.user.last_name',
    ],
    'term detail > sections by highschool': [
        'ce_url', 'class_number', 'co_reqs', 'course.credit_hours',
        'course.name', 'course.title', 'highschool.name', 'id',
        'registration_term.label', 'section_number', 'status',
        'teacher.user.first_name', 'teacher.user.last_name',
    ],
    'student detail > files (student profile)': [
        'description', 'id', 'media', 'term.label', 'uploaded_on',
    ],
}


# Paths a table's registries name that the feed does not answer. Every one is
# correct behaviour, not a gap; the test below fails if one starts resolving,
# so the change gets looked at rather than absorbed.
#
# Three causes:
#
#   shared JS -- instructors_table.js backs the teacher, teacher-course and
#   highschool-teacher feeds across four profiles, and support_docs_table.js
#   two, so a row.<path> grep attributes one profile's fields to the others.
#   Nothing reads these on the table they are listed under.
#
#   correctly trimmed -- the serializer ships the field, but the profile does
#   not name it as a column and it is not in datatables_always_serialize, so
#   DatatablesRenderer drops it. Exactly what the original serializers did:
#   account_verified on the dirty and missing-recommendation student profiles,
#   `since` on the hs-admins index, term.label on the two term-detail section
#   profiles, and ce_url on hs_student_detail -- that one deliberately, since
#   the profile omits the Edit action because it links into /ce/, which HS
#   admins may not reach.
#
#   absent from the fixture -- meta.manage_student_recommendation is served
#   (the whole `meta` JSONField is), but the fixture row's dict is empty.
KNOWN_UNANSWERED = {
    '/ce/highschool_admins/': [
        'meta.manage_student_recommendation', 'since',
    ],
    '/ce/instructors/': [
        'course.name', 'teacher.ce_url', 'teacher.user.email',
        'teacher.user.first_name', 'teacher.user.last_name',
        'teacher_highschool.highschool',
        'teacher_highschool.teacher',
    ],
    'highschool detail > instructors': [
        'course.name', 'id', 'teacher_highschool.highschool',
        'teacher_highschool.teacher',
    ],
    'course detail > instructors': [
        'course.name', 'teacher.ce_url', 'teacher.user.email',
        'teacher.user.first_name', 'teacher.user.last_name',
    ],
    'course detail > administrators': [
        'user.email', 'user.first_name', 'user.last_login',
        'user.last_name',
    ],
    'student detail > files': [
        'student.ce_url', 'student.user.first_name',
        'student.user.last_name',
    ],
    'hs admin detail > roles': [
        'meta.manage_student_recommendation',
    ],
    '/ce/students/ dirty': [
        'account_verified',
    ],
    '/ce/students/ missing recommendation': [
        'account_verified',
    ],
    'cohort detail > instructors': [
        'teacher.ce_url', 'teacher.user.email',
        'teacher.user.first_name', 'teacher.user.last_name',
    ],
    'hs student detail > registrations': [
        'ce_url',
    ],
    'term detail > sections by course': [
        'term.label',
    ],
    'term detail > sections by highschool': [
        'term.label',
    ],
    'student detail > files (student profile)': [
        'student.ce_url', 'student.user.first_name',
        'student.user.last_name',
    ],
}


class TableSerializerContractTests(TestCase):
    """MISSING means the table renders a blank column."""

    @classmethod
    def setUpTestData(cls):
        TableContractFixture.build()
        cls.user = CustomUser.objects.create_superuser(
            username='contract', email='contract@example.com', password='x')
        group, _ = Group.objects.get_or_create(name='ce')
        cls.user.groups.add(group)

    def test_the_registries_still_say_what_the_contract_was_built_from(self):
        """The contract is frozen data, so it has to be re-derived when a table
        changes. Adding a column or a render callback lands here first: the
        derived path set stops matching, and whoever added it decides whether
        the new path belongs in FROZEN_PATHS (the serializer must answer it) or
        in KNOWN_UNANSWERED (it does not, and that is understood).
        """
        for label, module, variant, js, _, _ in TABLE_CONTRACTS:
            with self.subTest(table=label):
                _, derived = paths_for(module, variant, js)
                recorded = (set(FROZEN_PATHS[label])
                            | set(KNOWN_UNANSWERED.get(label, ())))
                self.assertEqual(
                    derived, recorded,
                    f'{label}: the table now reads '
                    f'{sorted(derived - recorded)} more and '
                    f'{sorted(recorded - derived)} fewer paths than the '
                    f'contract records')

    def test_every_contracted_path_is_present_in_the_feed(self):
        for label, module, variant, js, basename, extra in TABLE_CONTRACTS:
            with self.subTest(table=label):
                columns, _ = paths_for(module, variant, js)
                rows, _ = render_feed(basename, columns, extra, self.user)
                self.assertTrue(
                    rows, f'{label} ({basename}): no rows to check')
                missing = [p for p in FROZEN_PATHS[label]
                           if dig(rows[0], p) is _MISSING]
                self.assertEqual(
                    missing, [],
                    f'{label} ({basename}): the serializer no longer answers '
                    f'{missing}; those columns will render blank')

    def test_the_known_gaps_have_not_quietly_been_filled(self):
        """If one of these starts resolving, the gap was fixed -- move it into
        FROZEN_PATHS so it stays fixed."""
        for label, module, variant, js, basename, extra in TABLE_CONTRACTS:
            gaps = KNOWN_UNANSWERED.get(label)
            if not gaps:
                continue
            with self.subTest(table=label):
                columns, _ = paths_for(module, variant, js)
                rows, _ = render_feed(basename, columns, extra, self.user)
                filled = [p for p in gaps if dig(rows[0], p) is not _MISSING]
                self.assertEqual(
                    filled, [],
                    f'{label} ({basename}): {filled} now resolves; move it to '
                    f'FROZEN_PATHS')

    def test_no_feed_ships_more_than_its_payload_budget(self):
        for label, module, variant, js, basename, extra in TABLE_CONTRACTS:
            with self.subTest(table=label):
                columns, _ = paths_for(module, variant, js)
                rows, response = render_feed(
                    basename, columns, extra, self.user)
                self.assertTrue(rows, f'{label}: no rows to measure')
                per_row = len(response.content) / len(rows)
                budget = PAYLOAD_BUDGETS[basename]
                self.assertLessEqual(
                    per_row, budget,
                    f'{label} ({basename}): {per_row:.0f} B/row exceeds the '
                    f'{budget} B budget')


# Feeds that have a narrowed serializer bound. Values, not just presence, are
# compared against the original for these.
SLIMMED_FEEDS = {
    'registration', 'class_section', 'highschool-teacher', 'teacher-course',
    'student', 'student-note', 'student_support_docs',
    'hs-administrator-position', 'course_administrator', 'course', 'teacher',
    'hs-administrator-access-request', 'drop_wd_req',
}
# 'highschool' is absent on purpose: it keeps its original serializer, so
# there is nothing to compare it against.


class SlimSerializerMatchesTheOriginalTests(TestCase):
    """A narrowed serializer must return the same *values*, not just the same
    keys.

    Presence is the cheap half of the contract and the contract test above
    covers it. The expensive half is format, and nothing else catches it: the
    originals declare reviewed_on as a CharField rather than a date field,
    created_on with a '%m/%d/%Y %I:%M %p' format, and has_recommendation /
    needs_recommendation as the strings 'Yes'/'No'. A narrowed copy that
    re-declares any of those the obvious way keeps every key, passes every
    presence check, and quietly changes what the table renders --
    registrations_table.js compares has_signed_* to the string 'True'.
    """

    @classmethod
    def setUpTestData(cls):
        TableContractFixture.build()
        cls.user = CustomUser.objects.create_superuser(
            username='parity', email='parity@example.com', password='x')
        group, _ = Group.objects.get_or_create(name='ce')
        cls.user.groups.add(group)

    def _both(self, basename, columns, extra):
        from unittest import mock

        from cis.serializers import tables

        slim_rows, _ = render_feed(basename, columns, extra, self.user)
        # The viewsets call tables.datatables_serializer through the module, so
        # patching the module attribute reaches all of them.
        with mock.patch.object(
                tables, 'datatables_serializer',
                side_effect=lambda view, _slim: view.serializer_class):
            full_rows, _ = render_feed(basename, columns, extra, self.user)
        return slim_rows, full_rows

    def test_the_patch_actually_swaps_the_serializer(self):
        """Guard on the guard: if the patch missed, both sides would be the
        narrowed output and every comparison below would trivially pass."""
        def keys(obj):
            if isinstance(obj, dict):
                return sum(1 + keys(v) for v in obj.values())
            if isinstance(obj, list):
                return sum(keys(v) for v in obj)
            return 0

        label, module, variant, js, basename, extra = next(
            row for row in TABLE_CONTRACTS if row[4] == 'registration')
        columns, _ = paths_for(module, variant, js)
        slim_rows, full_rows = self._both(basename, columns, extra)
        # Counted recursively: the trimmed serializers subclass the originals
        # and keep every top-level field, so the two rows are the same width
        # at depth 0 and differ only inside the nests.
        self.assertLess(
            keys(slim_rows[0]), keys(full_rows[0]),
            'the full serializer did not produce a deeper row; the patch in '
            '_both is not reaching the viewset')

    def test_every_contracted_value_matches_the_original(self):
        seen = set()
        for label, module, variant, js, basename, extra in TABLE_CONTRACTS:
            if basename not in SLIMMED_FEEDS or basename in seen:
                continue
            seen.add(basename)
            with self.subTest(feed=basename):
                columns, _ = paths_for(module, variant, js)
                slim_rows, full_rows = self._both(basename, columns, extra)
                self.assertTrue(slim_rows and full_rows)
                mismatches = []
                for path in FROZEN_PATHS[label]:
                    slim_value = dig(slim_rows[0], path)
                    full_value = dig(full_rows[0], path)
                    if full_value is _MISSING:
                        # Trimmed out of the original by the renderer; the
                        # narrowed serializer answering it is an improvement,
                        # not a mismatch.
                        continue
                    if slim_value != full_value:
                        mismatches.append(
                            f'{path}: {slim_value!r} != {full_value!r}')
                self.assertEqual(
                    mismatches, [],
                    f'{basename}: the narrowed serializer changed values:\n  '
                    + '\n  '.join(mismatches))
