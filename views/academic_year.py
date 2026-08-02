import csv
import io

from django.db.models import Q, Count
from django.views import View
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render

from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.urls import reverse
from django.views.decorators.http import require_POST

from cis.models.term import AcademicYear
from cis.campus_gate import scope_queryset_by_campus
from cis.forms.term import AcademicYearForm, MigrateAcademicYearForm, AcademicYearUploadForm
from cis.menu import cis_menu, draw_menu
from cis.services.table_configs import get_table_config
from cis.services.comparison import build_compare_context
build_academic_years_table_config = get_table_config('academic_years_table').build_config

from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.term import AcademicYearSerializer, AcademicYearListSerializer
from cis.utils import CIS_user_only
from myce.component_registry.academic_year import academic_year_tabs

class AcademicYearViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AcademicYearListSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        # Per-year counts over all of the year's terms' ClassSections
        # (AcademicYear <- Term.academic_year <- ClassSection.term). distinct=True
        # keeps the shared multi-hop join from inflating the counts. Real
        # annotations (not method fields) so server-side sorting works.
        records = AcademicYear.objects.select_related('campus').annotate(
            num_sections=Count('term__classsection', distinct=True),
            num_highschools=Count('term__classsection__highschool', distinct=True),
            num_teachers=Count('term__classsection__teacher', distinct=True),
            num_courses=Count('term__classsection__course', distinct=True),
        )
        # Campus gate: ce staff see only academic years for their processable
        # campuses (+ null-campus). Superusers/non-ce unchanged.
        return scope_queryset_by_campus(records, self.request.user)

from django.views.decorators.clickjacking import xframe_options_exempt


def delete_record(request, record_id):
    record = get_object_or_404(AcademicYear, pk=record_id)

    try:
        record.delete()
    except Exception as e:
        return JsonResponse({
            'message': 'Unable to delete record' + str(e),
            'status': 'error'
        }, status=400)
    return JsonResponse({
        'message': 'Successfully deleted record',
        'status': 'success'
    })

def tab(request, record_id, tab_slug):
    """Render a single Academic Year detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(AcademicYear, pk=record_id)
    return academic_year_tabs.render_tab(request, record, tab_slug)


@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/term/academic_year.html'    
    record = get_object_or_404(AcademicYear, pk=record_id)
    
    migration_form = MigrateAcademicYearForm(record=record)
    form = AcademicYearForm(instance=record)

    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_academic_year':
            migration_form = MigrateAcademicYearForm(
                record=record, data=request.POST
            )

            if migration_form.is_valid():
                success, message = migration_form.save(request, record)

                if not success:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Your request was processed with some errors.<br>' + '<br>'.join(message),
                        'list-group-item-warning')
                else:
                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully completed request. ' + ','.join(message),
                        'list-group-item-success')
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Please correct the errors and try again',
                    'list-group-item-danger')
        else:
            form = AcademicYearForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:academic_year', record_id=record_id)
    
    from myce.component_registry.academic_year import academic_year_actions

    return render(
        request,
        template, {
            'detail_actions': academic_year_actions.for_scope('detail', request.user),
            'detail_tabs': academic_year_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:academic_year_tab', args=[record.id, slug]),
            ),
            'menu': draw_menu(cis_menu, 'classes', 'academic_years'),
            'record': record,
        })

def import_academic_years_from_file(request):
    """Handle CSV file upload for Academic Year import."""
    from cis.services.importers import AcademicYearRow

    form = AcademicYearUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = AcademicYear.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:academic_year_add_new')

            file_name = "academic_year_import_results.csv"
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="{file_name}"'

            writer = csv.writer(response)
            writer.writerow(result['records'][0].keys())
            for row in result['records']:
                writer.writerow(row.values())
            return response

        messages.add_message(
            request,
            messages.SUCCESS,
            'There was an error processing the file.' + result.get('message', ''),
            'list-group-item-danger')
        return redirect('cis:academic_year_add_new')


def download_academic_year_template(request):
    """Download a blank CSV template with the correct headers for Academic Year import."""
    from cis.services.importers import AcademicYearRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="academic_year_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(AcademicYearRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    from cis.services.importers import AcademicYearRow

    base_template = 'cis/logged-base.html'
    template = 'cis/term/academic_year-add_new.html'
    ajax = request.GET.get('ajax', None)
    upload_form = AcademicYearUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import Academic Years":
            return import_academic_years_from_file(request)

        form = AcademicYearForm(request.POST)
        ajax = request.POST.get('ajax', None)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            if ajax == '1':
                data = {
                    'status':'success',
                    'message':'Successfully added new record',
                    'new_record_id':record.id,
                    'new_record_name':record.name
                }
                return JsonResponse(data)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success')
            return redirect('cis:academic_years')
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ' '.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = AcademicYearForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    context = {
        'form': form,
        'ajax': ajax,
        'base_template': base_template,
        'menu': draw_menu(cis_menu, 'classes', 'academic_years')
    }

    if not ajax:
        context['upload_form'] = upload_form
        context['schema_fields'] = AcademicYearRow.field_definitions()
        context['required_header'] = AcademicYearRow.csv_headers()

    return render(request, template, context)


def do_bulk_action(request):
    from myce.component_registry.academic_year import academic_year_actions
    action = request.GET.get('action')
    if request.method == 'POST':
        action = request.POST.get('action')
    return academic_year_actions.dispatch(request, action)


@require_POST
def delete_academic_years(request):
    """Bulk-delete selected academic years. POST-only + CSRF-protected: this is
    a destructive action and must not be reachable via GET. Years still
    referenced by a Term are protected (Term.academic_year is on_delete=PROTECT)
    and reported as failures rather than deleted."""
    ids = request.POST.getlist('ids[]')
    deleted, failed = 0, 0
    for pk in ids:
        try:
            AcademicYear.objects.get(pk=pk).delete()
            deleted += 1
        except Exception:
            failed += 1
    msg = f'Deleted {deleted} academic year(s).'
    if failed:
        msg += f' {failed} could not be deleted (in use by term(s)).'
    return JsonResponse({
        'action': 'display',
        'status': 'success' if not failed else 'warning',
        'title': 'Delete Academic Years',
        'message': msg,
    })


def index(request):
    '''
    Academic Year Role search and index page for staff
    '''
    from myce.component_registry.academic_year import academic_year_actions
    menu = draw_menu(cis_menu, 'classes', 'academic_years')
    template = 'cis/term/academic_years.html'

    # Flatten the grouped bulk-actions registry ({group: {actions: {slug: a}}})
    # into a flat {slug: action} mapping for the shared table partial.
    grouped = academic_year_actions.for_scope('bulk', request.user)
    flat_bulk_actions = {}
    for group in grouped.values():
        for slug, action in group.get('actions', {}).items():
            flat_bulk_actions[slug] = action

    index_table = build_academic_years_table_config(
        variant='academic_years_index',
        api_url='/ce/api/academic-year?format=datatables',
        details_prefix='/ce/academic_year/',
        bulk_actions=flat_bulk_actions or None,
    )

    context = {
        'menu': menu,
        'page_title': 'Academic Years',
        'api_url': '/ce/api/academic-year?format=datatables',
        'bulk_actions': grouped,
        'index_table': index_table,
        'urls': {
            'details_prefix': '/ce/academic_year/',
            'add_new': 'cis:academic_year_add_new'
        }
    }
    context.update(build_compare_context(request, 'academic_year'))

    return render(request, template, context)