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
from django.views.decorators.clickjacking import xframe_options_exempt

from cis.models.term import Term
from cis.campus_gate import scope_queryset_by_campus
from cis.forms.term import AcademicYearForm, TermForm, MigrateTermForm, TermUploadForm
from cis.menu import cis_menu, draw_menu
from cis.services.table_configs import get_table_config
from cis.services.comparison import build_compare_context
build_terms_table_config = get_table_config('terms_table').build_config
from myce.component_registry.term import term_actions, term_tabs

# Ensure ethos section handlers are registered via their decorators
try:
    import importlib.util as _util
    if _util.find_spec('ethos.ethos'):
        import ethos.ethos.views.sections  # noqa: F401
    else:
        import ethos.views.sections  # noqa: F401
except ImportError:
    pass

import cis.actions.term  # noqa: F401  (registers term detail/index actions)


from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.term import TermSerializer
from cis.utils import CIS_user_only

class TermViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TermSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        academic_year_id = self.request.GET.get('academic_year', None)
        # Per-term counts over the term's ClassSections (default `term` FK,
        # reverse query name `classsection`). All four aggregates traverse the
        # same single join, so distinct=True yields correct, non-inflated counts.
        result = Term.objects.select_related(
            'academic_year__campus', 'parent').annotate(
            num_sections=Count('classsection', distinct=True),
            num_highschools=Count('classsection__highschool', distinct=True),
            num_teachers=Count('classsection__teacher', distinct=True),
            num_courses=Count('classsection__course', distinct=True),
        )

        if academic_year_id:
            result = result.filter(academic_year__id=academic_year_id)

        # Campus gate: a term's campus is its academic year's campus. ce staff
        # see only terms whose academic year is in a processable campus (+ null).
        result = scope_queryset_by_campus(
            result, self.request.user, campus_path='academic_year__campus')

        return result.order_by('-code')

def tab(request, record_id, tab_slug):
    """Render a single Term detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(Term, pk=record_id)
    return term_tabs.render_tab(request, record, tab_slug)


@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/term/term.html'    
    record = get_object_or_404(Term, pk=record_id)
    form = TermForm(instance=record)

    migration_form = MigrateTermForm(record=record)

    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_term':
            migration_form = MigrateTermForm(
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
            form = TermForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:term', record_id=record_id)
    
    return render(
        request,
        template, {
            'detail_actions': term_actions.for_scope('detail', request.user),
            'detail_tabs': term_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:term_tab', args=[record.id, slug]),
            ),
            'menu': draw_menu(cis_menu, 'classes', 'terms'),
            'record': record,
        })

def do_bulk_action(request):
    action = request.POST.get('action') or request.GET.get('action')

    if action == 'delete_terms':
        ids = request.POST.getlist('ids[]')
        deleted, failed = 0, []
        for pk in ids:
            try:
                Term.objects.get(pk=pk).delete()
                deleted += 1
            except Exception as e:
                failed.append(str(e))
        msg = f'Deleted {deleted} term(s).'
        if failed:
            msg += f' {len(failed)} could not be deleted.'
        return JsonResponse({
            'outcome': 'call',
            'fn': 'onBulkActionComplete',
            'args': {
                'title': 'Delete Terms',
                'message': msg,
                'status': 'success' if not failed else 'warning',
            },
        })

    return term_actions.dispatch(request, action)


def delete_record(request, record_id):
    record = get_object_or_404(Term, pk=record_id)

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

def import_terms_from_file(request):
    """Handle CSV file upload for Term import."""
    from cis.services.importers import TermRow

    form = TermUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = Term.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:term_add_new')

            file_name = "term_import_results.csv"
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
        return redirect('cis:term_add_new')


def download_term_template(request):
    """Download a blank CSV template with the correct headers for Term import."""
    from cis.services.importers import TermRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="term_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(TermRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    from cis.services.importers import TermRow

    base_template = 'cis/logged-base.html'
    template = 'cis/term/term-add_new.html'
    ajax = request.GET.get('ajax', None)
    upload_form = TermUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import Terms":
            return import_terms_from_file(request)

        form = TermForm(request.POST)
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
            return redirect('cis:terms')
        else:
            if ajax == '1':
                data = {
                    'status':'error',
                    'message': ' '.join([' '.join(x for x in l) for l in list(form.errors.values())])
                }
                return JsonResponse(data)
    else:
        form = TermForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    context = {
        'form': form,
        'ajax': ajax,
        'base_template': base_template,
        'menu': draw_menu(cis_menu, 'classes', 'terms')
    }

    if not ajax:
        context['upload_form'] = upload_form
        context['schema_fields'] = TermRow.field_definitions()
        context['required_header'] = TermRow.csv_headers()

    return render(request, template, context)

def index(request):
    '''
    Term Year Role search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'classes', 'terms')
    template = 'cis/term/terms.html'

    index_table = build_terms_table_config(
        variant='terms_index',
        api_url='/ce/api/term?format=datatables',
        details_prefix='/ce/term/',
        bulk_actions={
            'delete_terms': {
                'label': 'Delete Selected',
                'icon': 'fas fa-trash',
                'btn_class': 'btn-danger',
                'confirm': 'Delete selected term(s)? This cannot be undone.',
            },
            'assign_parent': {
                'label': 'Assign Parent Term',
                'icon': 'fas fa-sitemap',
                'btn_class': 'btn-primary',
            },
        },
    )

    context = {
        'menu': menu,
        'page_title': 'Terms',
        'api_url': '/ce/api/term?format=datatables',
        'index_table': index_table,
        'urls': {
            'details_prefix': '/ce/term/',
            'add_new': 'cis:term_add_new'
        }
    }
    context.update(build_compare_context(request, 'term'))

    return render(request, template, context)
