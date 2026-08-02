from django.contrib.auth.decorators import user_passes_test
from django.db.models import Count, F, Value, CharField
from django.db.models.functions import Concat
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from rest_framework import viewsets

from cis.utils import (
    CIS_user_only, INSTRUCTOR_user_only, HSADMIN_user_only,
    user_has_cis_role, user_has_highschool_admin_role,
)
from cis.menu import cis_menu, draw_menu

from cis.campus_gate import (
    scope_queryset_by_campus, get_accessible_campuses,
)
from cis.utils import get_default_campus
from cis.models.teacher import TeacherCourseCertificate
from cis.serializers.credentials import (
    CredentialExpirySerializer, CredentialSummarySerializer,
)
from cis.forms.credential_bulk import CredentialBulkUpdateForm


def _window_filter(days):
    """Q object: renewal_due_date (renewal_required_by or expires_on) in window.

    Thin wrapper over the shared TeacherCourseCertificate.due_within_q helper.
    """
    return TeacherCourseCertificate.due_within_q(days)


class CredentialExpiryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CredentialExpirySerializer
    permission_classes = [CIS_user_only | INSTRUCTOR_user_only | HSADMIN_user_only]

    def get_queryset(self):
        # Default 'all' (no window filter); the dropdown lets the user narrow
        # to certificates due within 30/60/90 days.
        days = self.request.GET.get('days', 'all')
        highschool_id = self.request.GET.get('highschool_id')
        status = self.request.GET.get('status')
        campus = self.request.GET.get('campus', '').strip()

        records = TeacherCourseCertificate.objects.select_related(
            'teacher_highschool__teacher__user',
            'teacher_highschool__highschool',
            'course',
        ).annotate(
            # Real annotations so DataTables can order/search by these columns —
            # the filter backend resolves the column NAME against the ORM, which
            # SerializerMethodFields / nested source traversals cannot satisfy.
            instructor_name=Concat(
                'teacher_highschool__teacher__user__last_name',
                Value(', '),
                'teacher_highschool__teacher__user__first_name',
                output_field=CharField(),
            ),
            highschool_name=F('teacher_highschool__highschool__name'),
            course_name=F('course__name'),
        )

        # Role scope (also the object-level check, since retrieve() filters
        # through get_queryset()):
        #   ce             -> all certificates
        #   highschool_admin -> certificates for teachers in their high schools
        #   instructor     -> only their own certificates
        user = self.request.user
        if user_has_cis_role(user):
            # ce staff are further scoped to their processable campuses (the
            # certificate's campus is its course's campus).
            records = scope_queryset_by_campus(
                records, user, campus_path='course__campus',
                selected_campus=campus or None)
        elif user_has_highschool_admin_role(user):
            hs_ids = user.get_highschools_for_admin()
            records = records.filter(teacher_highschool__highschool__id__in=hs_ids)
        else:
            records = records.filter(teacher_highschool__teacher__user=user)

        if days in ('30', '60', '90'):
            records = records.filter(_window_filter(days))

        if highschool_id:
            records = records.filter(
                teacher_highschool__highschool__id=highschool_id)
        if status:
            records = records.filter(status__iexact=status)

        return records.order_by('expires_on', 'renewal_required_by')


class CredentialSummaryViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CredentialSummarySerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        days = self.request.GET.get('days', 'all')
        group_by = self.request.GET.get('group_by', 'course')

        campus = self.request.GET.get('campus', '').strip()
        base = TeacherCourseCertificate.objects.all()
        # ce-only viewset: scope the summary counts to processable campuses.
        base = scope_queryset_by_campus(
            base, self.request.user, campus_path='course__campus',
            selected_campus=campus or None)
        if days in ('30', '60', '90'):
            base = base.filter(_window_filter(days))

        # Group-by idiom: annotate the grouping label as a real `group`
        # annotation, then values(...).annotate(count) groups by it. Exposing
        # `group` as an annotation (not a SerializerMethodField source) lets the
        # rest_framework_datatables backend order/search on it without a
        # FieldError.
        if group_by == 'highschool':
            group_field = 'teacher_highschool__highschool__name'
            values = ['group']
            order = ['group']
        else:
            group_field = 'course__name'
            # The by-course summary also breaks down by certificate status:
            # one row per (course, status) with its count.
            values = ['group', 'status']
            order = ['group', 'status']

        return (
            base.annotate(group=F(group_field))
            .values(*values)
            .annotate(count=Count('id'))
            .order_by(*order)
        )


@user_passes_test(user_has_cis_role, login_url='/')
def index(request):
    """The /ce/credentials/ dashboard page."""
    from cis.services.table_configs import get_table_config
    build = get_table_config('credentials_table').build_config

    menu = draw_menu(cis_menu, 'instructors', 'credentials')
    return render(request, 'cis/credentials/index.html', {
        'menu': menu,
        'page_title': 'Course Certificates',
        'summary_api_url': '/ce/api/credential-summary?format=datatables',
        'accessible_campuses': get_accessible_campuses(request.user),
        'default_campus': get_default_campus(request.user),
        'credentials_table': build(
            variant='credentials_index',
            api_url='/ce/api/credential-expiry?format=datatables',
            bulk_actions={
                'bulk_update': {
                    'label': 'Update Dates / Status',
                    'icon': 'fas fa-edit',
                    'btn_class': 'btn-primary',
                    'confirm': None,
                },
            },
            bulk_actions_url=reverse('cis:credential_bulk_actions'),
            filter_form_selector='#credentials_filter',
        ),
    })


@user_passes_test(user_has_cis_role, login_url='/')
def bulk_actions(request):
    """GET renders the bulk form modal; POST applies it."""
    template = 'cis/credentials/bulk_action.html'

    if request.method == 'POST':
        form = CredentialBulkUpdateForm(data=request.POST)
        if form.is_valid():
            count = form.apply()
            return JsonResponse({
                'status': 'success',
                'message': f'Updated {count} certificate(s).',
                'action': 'reload_table',
            })
        return JsonResponse({
            'status': 'error',
            'message': 'Please correct the errors and try again.',
            'errors': form.errors.as_json(),
        }, status=400)

    ids = ','.join(request.GET.getlist('ids[]'))
    form = CredentialBulkUpdateForm(ids)
    return render(request, template, {
        'title': 'Update Credential Dates / Status',
        'form': form,
        'form_id': 'frm_credential_bulk',
        'form_action': str(reverse('cis:credential_bulk_actions')),
    })
