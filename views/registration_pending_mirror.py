"""Preview of registrations queued for the next SIS mirror run."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render
from django.urls import reverse
from rest_framework import viewsets

from cis.menu import draw_menu, cis_menu
from cis.models.section import StudentRegistration
from cis.utils import CIS_user_only, user_has_cis_role
from cis.serializers.registration import PendingSisMirrorRegistrationSerializer
from cis.services.table_configs import get_table_config

build_pending_mirror_table_config = get_table_config('pending_sis_mirror_table').build_config


class PendingSisMirrorRegistrationViewSet(viewsets.ReadOnlyModelViewSet):
    """DataTables JSON feed for registrations queued to mirror to SIS."""
    serializer_class = PendingSisMirrorRegistrationSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        return (
            StudentRegistration.objects
            .pending_sis_mirror()
            .select_related(
                'student__user',
                'class_section__course',
                'class_section__term',
                'class_section__highschool',
            )
            .order_by('student__user__last_name', 'student__user__first_name')
        )


@login_required
@user_passes_test(user_has_cis_role, login_url='/')
def pending_mirror_page(request):
    menu = draw_menu(cis_menu, 'students', 'registrations_pending_mirror')
    api_url = reverse('cis:pending_sis_mirror_registrations-list') + '?format=datatables'
    return render(request, 'cis/registrations/pending_mirror.html', {
        'menu': menu,
        'pending_mirror_table': build_pending_mirror_table_config(
            variant='pending_mirror',
            api_url=api_url,
        ),
    })
