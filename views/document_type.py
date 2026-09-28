"""CE Document Types page: /ce/document_types/ (#45 follow-up).

The CE-managed vocabulary behind both course document requirements and
student uploads. Types are added and edited here and retired by making them
Inactive -- never deleted, since both FKs pointing at DocumentType are PROTECT.

Campus scoping follows campus_gate.py: the list shows the user's campuses plus
legacy unassigned types, the edit page is gated on the type's campus, and the
form only offers the user's campuses.
"""
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.clickjacking import xframe_options_exempt

from rest_framework import viewsets

from cis.campus_gate import campus_gate, scope_queryset_by_campus
from cis.forms.course import DocumentTypeForm
from cis.menu import cis_menu, draw_menu
from cis.models.course import DocumentType
from cis.serializers.course import DocumentTypeSerializer
from cis.services.table_configs import get_table_config
from cis.utils import CIS_user_only

API_URL = '/ce/api/document-type/?format=datatables'
DETAILS_PREFIX = '/ce/document_type/'


class DocumentTypeViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentTypeSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        records = DocumentType.objects.select_related('campus')
        return scope_queryset_by_campus(records, self.request.user)


def _menu():
    return draw_menu(cis_menu, 'classes', 'document_types')


def _table_config():
    """The tenant's table config, or None if it doesn't ship one yet.

    Resolved here rather than at import time: get_table_config() is a bare
    import, and a module-level call would turn a tenant that lags on
    myce_tenant_configs into an ImportError for the whole cis URLconf.
    """
    try:
        module = get_table_config('document_types_table')
    except ImportError:
        return None
    return module.build_config(
        variant='document_types_index',
        api_url=API_URL,
        details_prefix=DETAILS_PREFIX,
    )


def index(request):
    context = {
        'menu': _menu(),
        'page_title': 'Document Types',
        'index_table': _table_config(),
    }
    if context['index_table'] is None:
        context['records'] = scope_queryset_by_campus(
            DocumentType.objects.select_related('campus'), request.user
        ).order_by('campus__name', 'label')
    return render(request, 'cis/document_type/document_types.html', context)


def add_new(request):
    if request.method == 'POST':
        form = DocumentTypeForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.add_message(
                request, messages.SUCCESS,
                'Successfully added document type',
                'list-group-item-success')
            return redirect('cis:document_types')
    else:
        form = DocumentTypeForm(user=request.user)

    return render(request, 'cis/document_type/document_type-add_new.html', {
        'form': form,
        'menu': _menu(),
        'page_title': 'Add Document Type',
    })


@xframe_options_exempt
@campus_gate(DocumentType, mode='page')
def detail(request, record_id):
    record = get_object_or_404(DocumentType, pk=record_id)

    if request.method == 'POST':
        form = DocumentTypeForm(request.POST, instance=record, user=request.user)
        if form.is_valid():
            form.save()
            messages.add_message(
                request, messages.SUCCESS,
                'Successfully updated document type',
                'list-group-item-success')
            return redirect('cis:document_type', record_id=record_id)
    else:
        form = DocumentTypeForm(instance=record, user=request.user)

    return render(request, 'cis/document_type/document_type.html', {
        'form': form,
        'record': record,
        'menu': _menu(),
        'page_title': record.label,
    })
