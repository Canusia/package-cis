"""Host-side registration-detail actions (registered on registration_actions)."""
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse

from cis.models.section import StudentRegistration
from cis.services.tenant_services import get_tenant_service
from myce.component_registry.registration import registration_actions


@registration_actions.action(
    'sis', label='Look up Section Registration ID', icon='fa fa-id-card',
    btn_class='btn-info', scope=['detail'], method='form')
def lookup_section_registration_id(request):
    """Resolve a registration's Ethos section-registration GUID and, on
    confirmation, save it to StudentRegistration.sis_id."""
    ethos_identity = get_tenant_service('ethos_identity')

    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'SIS Lookup', 'message': 'No registration selected.'})

    try:
        registration = StudentRegistration.objects.select_related(
            'student__user', 'class_section').get(pk=ids[0])
    except StudentRegistration.DoesNotExist:
        return JsonResponse({'outcome': 'alert', 'status': 'error',
                             'title': 'SIS Lookup', 'message': 'Registration not found.'})

    if request.POST.get('action_confirmed'):
        new_sis_id = (request.POST.get('new_sis_id') or '').strip() or None
        changes, error = ethos_identity.apply_section_registration_id(
            registration, new_sis_id, actor=request.user)
        if error:
            return JsonResponse({'outcome': 'alert', 'status': 'error',
                                 'title': 'SIS Lookup', 'message': error})
        if not changes:
            return JsonResponse({'outcome': 'alert', 'status': 'info',
                                 'title': 'SIS Lookup', 'message': 'No change — SIS ID already set.'})
        return JsonResponse({'outcome': 'call', 'fn': 'onActionComplete',
                             'args': {'title': 'Success',
                                      'message': 'Section registration SIS ID saved.',
                                      'status': 'success'}})

    if not registration.student.sis_id or not registration.class_section.sis_id:
        return JsonResponse({'outcome': 'alert', 'status': 'warning', 'title': 'SIS Lookup',
                             'message': 'Missing student SIS ID or section SIS ID — cannot look up.'})

    found = ethos_identity.lookup_section_registration_id(registration)
    if not found:
        return JsonResponse({'outcome': 'alert', 'status': 'warning', 'title': 'SIS Lookup',
                             'message': 'No matching section registration found in Ethos.'})

    current = str(registration.sis_id or '')
    html = render_to_string('cis/registrations/lookup_section_registration_id.html', {
        'title': 'Look up Section Registration ID',
        'registration': registration,
        'current_sis_id': current,
        'new_sis_id': found,
        'has_changes': str(found) != current,
        'form_action': reverse('cis:registration_bulk_actions'),
        'action_slug': 'lookup_section_registration_id',
        'ids': [str(registration.id)],
    }, request=request)
    return JsonResponse({'outcome': 'modal', 'html': html})
