"""Triage list of registrations whose last SIS mirror attempt failed."""
import csv
import uuid

from django.utils.http import content_disposition_header

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from rest_framework import viewsets

from cis.campus_gate import (
    get_accessible_campuses, scope_queryset_by_campus,
)
from cis.menu import draw_menu, cis_menu
from cis.models.section import StudentRegistration
from cis.models.student import ParentConsent, StudentAgreement
from cis.models.term import Term
from cis.utils import (
    CIS_user_only, YES_NO_OPTIONS, registration_terms,
    user_has_cis_role,
)
from cis.serializers.registration import FailedMirrorRegistrationSerializer

# Serializer key -> CSV header. Shared by the export so its columns cannot
# drift from the ones the table feed exposes.
EXPORT_COLUMNS = (
    ('student_name',       'Student'),
    ('student_psid',       'PSID'),
    ('class_section_str',  'Section'),
    ('term_code',          'Term'),
    ('status_display',     'Status'),
    ('needs_mirroring',    'Needs Mirroring'),
    ('last_mirror_at',     'Last Attempt'),
    ('last_log_status',    'HTTP'),
    ('last_mirror_error',  'Error'),
)


def failed_mirror_queryset():
    """Every registration whose last mirror attempt failed.

    Shared by the DataTables feed and the export-all endpoint so the export
    can never disagree with the page about what "failed" means.
    """
    return (
        StudentRegistration.objects
        .filter(last_mirror_status='failed')
        .select_related(
            'student__user',
            'class_section__course',
            'class_section__term',
            'class_section__highschool',
        )
        .prefetch_related('mirror_logs')
        .order_by('-last_mirror_at')
    )


def apply_filters(records, request):
    """Narrow the failed-mirror queryset by the page's filter bar.

    The controls are the ones on the Registrations tab (cis/registrations/
    index.html) and the query params carry the same names and sentinels, so
    RegistrationViewSet and this feed read a filter the same way. One
    deliberate difference: Registrations defaults an absent `term` to the
    active term, while a triage page must not silently hide failures from
    other terms -- here an absent/blank term means every term.

    Shared by the DataTables feed and the export so "Export All" returns what
    the filter bar is showing rather than the unfiltered table.
    """
    term = (request.GET.get('term') or '').strip()
    campus = (request.GET.get('campus') or '').strip()
    status = (request.GET.get('status') or '').strip()
    record_type = (request.GET.get('record_type') or '').strip()
    signed_student_agreement = (
        request.GET.get('signed_student_agreement') or '').strip()
    signed_parent_consent = (
        request.GET.get('signed_parent_consent') or '').strip()

    # '' / -1 / -3 all mean "no term filter" here (see docstring).
    if term in ('', '-1', '-3'):
        term = None

    if record_type == 'with_prereq':
        records = records.filter(
            Q(class_section__course__prereq=None) |
            Q(class_section__course__prereq='')
        )
    elif record_type == 'needs_mirroring':
        records = records.filter(needs_mirroring=True)
    elif record_type:
        # Same rule as a malformed term or campus. The dropdown only offers the
        # two above, but the Registrations tab's "sis_error" value reaches here
        # from a hand-typed or bookmarked URL, and returning every row for a
        # filter the user believes is applied is the failure this page exists
        # to avoid.
        return records.none()

    if term:
        if term == '-2':
            records = records.filter(
                class_section__term__in=registration_terms())
        else:
            # Anything that is not a sentinel is treated as a Term UUID; a
            # malformed value must not raise out of the DataTables feed.
            try:
                uuid.UUID(str(term))
            except (ValueError, AttributeError, TypeError):
                return records.none()
            records = records.filter(class_section__term__id=term)

    if status:
        records = records.filter(status=status)

    for value, model in ((signed_student_agreement, StudentAgreement),
                         (signed_parent_consent, ParentConsent)):
        if not value:
            continue
        signed = model.objects.all()
        if term == '-2':
            signed = signed.filter(term__in=registration_terms())
        elif term:
            signed = signed.filter(term__id=term)
        signed_ids = signed.values_list('student__id', flat=True)
        if value == '1':
            records = records.filter(student__id__in=signed_ids)
        else:
            records = records.exclude(student__id__in=signed_ids)

    # Campus for a registration resolves via class_section -> course -> campus.
    # Apply the dropdown's choice, then the ce-staff security scope on the same
    # path (a no-op for superusers and non-ce roles).
    if campus and campus != '-1':
        # Same rule as `term` above: a malformed id matches nothing, so return
        # nothing. Dropping the filter instead would render a full, unfiltered
        # table that the admin reads as scoped to one campus -- and Export All
        # would follow it out to CSV.
        try:
            uuid.UUID(str(campus))
        except (ValueError, AttributeError, TypeError):
            return records.none()
        records = records.filter(class_section__course__campus__id=campus)

    return scope_queryset_by_campus(
        records, request.user, campus_path='class_section__course__campus')


class FailedMirrorRegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    """DataTables JSON feed for failed mirror attempts."""
    serializer_class = FailedMirrorRegistrationSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        return apply_filters(failed_mirror_queryset(), self.request)


@login_required
@user_passes_test(user_has_cis_role, login_url='/')
def failed_mirror_page(request):

    menu = draw_menu(cis_menu, 'students', 'registrations_failed_mirror')
    # No default_campus: snippets/campus.html pre-selects whatever it is given,
    # and the table's first request is built from the form, so a default would
    # load the page already narrowed to one campus -- and narrow Export All
    # with it. Same reasoning as the term filter defaulting to every term: a
    # triage list must not quietly hide failures the admin can act on.
    return render(request, 'cis/registrations/failed_mirror.html', {
        'menu': menu,
        'data_url': reverse('cis:failed_mirror_registrations-list') + '?format=datatables',
        'export_url': reverse('cis:registrations_failed_mirror_export'),
        'campus': get_accessible_campuses(request.user),
        'terms': Term.objects.all().order_by('-academic_year__name'),
        'registration_status': StudentRegistration.STATUS_OPTIONS,
        'yes_no': YES_NO_OPTIONS,
    })


@login_required
@user_passes_test(user_has_cis_role, login_url='/')
def failed_mirror_export(request):
    """CSV of every failed-mirror registration matching the current filters.

    The table is server-side, so DataTables' own CSV button only ever sees the
    page currently loaded. This walks the whole queryset instead. The page
    appends its filter form to this URL, so the export narrows the same way
    the table does.

    Rows are built through FailedMirrorRegistrationSerializer -- the same one
    the table feed uses -- so a column added there shows up here too.
    """
    records = apply_filters(failed_mirror_queryset(), request)

    response = HttpResponse(content_type='text/csv')
    filename = 'failed_mirror_registrations_%s.csv' % (
        timezone.localtime().strftime('%Y%m%d_%H%M'))
    response['Content-Disposition'] = content_disposition_header(True, filename)

    writer = csv.writer(response)
    writer.writerow([header for _, header in EXPORT_COLUMNS])

    serializer = FailedMirrorRegistrationSerializer(records, many=True)
    for row in serializer.data:
        writer.writerow([_cell(row, key) for key, _ in EXPORT_COLUMNS])

    return response


def _cell(row, key):
    """Render one serialized value the way the table displays it."""
    value = row.get(key)
    if key == 'needs_mirroring':
        return 'Yes' if value else 'No'
    return '' if value is None else value
