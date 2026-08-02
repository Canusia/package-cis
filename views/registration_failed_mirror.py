"""Triage list of registrations whose last SIS mirror attempt failed."""
import csv

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from rest_framework import viewsets

from cis.menu import draw_menu, cis_menu
from cis.models.section import StudentRegistration
from cis.utils import CIS_user_only, user_has_cis_role
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


class FailedMirrorRegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    """DataTables JSON feed for failed mirror attempts."""
    serializer_class = FailedMirrorRegistrationSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        return failed_mirror_queryset()


@login_required
@user_passes_test(user_has_cis_role, login_url='/')
def failed_mirror_page(request):

    menu = draw_menu(cis_menu, 'students', 'registrations_failed_mirror')
    return render(request, 'cis/registrations/failed_mirror.html', {
        'menu': menu,
        'data_url': reverse('cis:failed_mirror_registrations-list') + '?format=datatables',
        'export_url': reverse('cis:registrations_failed_mirror_export'),
    })


@login_required
@user_passes_test(user_has_cis_role, login_url='/')
def failed_mirror_export(request):
    """CSV of every failed-mirror registration.

    The table is server-side, so DataTables' own CSV button only ever sees the
    page currently loaded. This walks the whole queryset instead.

    Rows are built through FailedMirrorRegistrationSerializer — the same one
    the table feed uses — so a column added there shows up here too.
    """
    records = failed_mirror_queryset()

    response = HttpResponse(content_type='text/csv')
    filename = 'failed_mirror_registrations_%s.csv' % (
        timezone.localtime().strftime('%Y%m%d_%H%M'))
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

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
