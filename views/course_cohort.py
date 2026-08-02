import csv
import io

from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse

from cis.models.course import (
    Cohort, Course
)
from ..models.section import ClassSection

from cis.forms.course import CohortForm, MigrateCohortForm, CohortUploadForm

from cis.menu import cis_menu, draw_menu
from cis.services.table_configs import get_table_config
build_instructors_table_config = get_table_config('instructors_table').build_config
build_cohorts_table_config = get_table_config('cohorts_table').build_config


from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.course import CohortSerializer
from cis.utils import CIS_user_only, get_foreign_key_references

class CohortViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [CIS_user_only]
    serializer_class = CohortSerializer
    def get_queryset(self):
        term = self.request.GET.get('term', '').strip()
        # campus = self.request.GET.get('campus', '').strip()
        campus = None
        
        try:
            if term:            
                if campus:
                    cohorts = ClassSection.objects.filter(
                        term__id=term,
                        campus__id=campus
                    ).distinct('course').values_list('course__cohort__id', flat=True)
                else:
                    cohorts = ClassSection.objects.filter(
                        term__id=term
                    ).distinct('course').values_list('course__cohort__id', flat=True)

                records = Cohort.objects.filter(
                    id__in=cohorts
                ).all()
            else:
                records = Cohort.objects.all()
        except:
            records = Cohort.objects.all()

        records = records.order_by('designator')
        return records

from django.views.decorators.clickjacking import xframe_options_exempt


def delete_record(request, record_id):
    record = get_object_or_404(Cohort, pk=record_id)

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

@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/course/cohort.html'    
    record = get_object_or_404(Cohort, pk=record_id)

    migration_form = MigrateCohortForm(record=record)
    form = CohortForm(instance=record)

    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_position':
            migration_form = MigrateCohortForm(
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
            form = CohortForm(request.POST, instance=record)

            if form.is_valid():
                record = form.save(commit=False)
                record.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:cohort', record_id=record_id)
    
    courses = Course.objects.filter(cohort=record.id)
    instructor_certificates = Cohort.get_instructor_certificates([record.id])

    return render(
        request,
        template, {
            'form': form,
            'page_title': f"Subject - {record.name}",
            'labels': {
                'all_items': 'All Subjects'
            },
            'urls': {
                'add_new': 'cis:cohort_add_new',
                'all_items': 'cis:cohorts'
            },
            'registration_summary_api_url': '/ce/api/registration-summary/?subject_id='+str(record.id) + '&format=datatables',
            'menu': draw_menu(cis_menu, 'classes', 'cohorts'),
            'record': record,
            'migration_form': migration_form,
            'courses': courses,
            'instructor_certificates': instructor_certificates,
            'instructors_table': build_instructors_table_config(
                variant='cohort_instructors',
                api_url=f'/ce/api/teacher-course/?cohort_id={record_id}&format=datatables',
                details_prefix='/ce/instructor/',
            ),
        })

def import_cohorts_from_file(request):
    """Handle CSV file upload for Cohort import."""
    from cis.services.importers import CohortRow

    form = CohortUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = Cohort.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:cohort_add_new')

            file_name = "cohort_import_results.csv"
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
        return redirect('cis:cohort_add_new')


def download_cohort_template(request):
    """Download a blank CSV template with the correct headers for Cohort import."""
    from cis.services.importers import CohortRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="cohort_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(CohortRow.csv_headers())
    return response


def add_new(request):
    '''
    Add new page
    '''
    from cis.services.importers import CohortRow

    base_template = 'cis/logged-base.html'
    template = 'cis/course/cohort-add_new.html'
    ajax = request.GET.get('ajax', None)
    upload_form = CohortUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import Cohorts":
            return import_cohorts_from_file(request)

        form = CohortForm(request.POST)
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
            return redirect('cis:cohort', record_id=record.id)

        if ajax == '1':
            data = {
                'status':'error',
                'message': ''.join([' '.join(x for x in l) for l in list(form.errors.values())])
            }
            return JsonResponse(data)
    else:
        form = CohortForm()

    if ajax == '1':
        base_template = 'cis/ajax-base.html'

    context = {
        'form': form,
        'page_title': "Add New",
        'labels': {
            'all_items': 'All Subjects'
        },
        'urls': {
            'add_new': 'cis:cohort_add_new',
            'all_items': 'cis:cohorts'
        },
        'ajax': ajax,
        'base_template': base_template,
        'menu': draw_menu(cis_menu, 'classes', 'cohorts')
    }

    if not ajax:
        context['upload_form'] = upload_form
        context['schema_fields'] = CohortRow.field_definitions()
        context['required_header'] = CohortRow.csv_headers()

    return render(request, template, context)

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'classes', 'cohorts')
    template = 'cis/course/cohorts.html'

    index_table = build_cohorts_table_config(
        variant='cohorts_index',
        api_url='/ce/api/cohort?format=datatables',
        details_prefix='/ce/cohort/',
    )

    return render(
        request,
        template, {
            'page_title': 'Subjects',
            'urls': {
                'add_new': 'cis:cohort_add_new',
                'details_prefix': '/ce/cohort/'
            },
            'menu': menu,
            'api_url': '/ce/api/cohort?format=datatables',
            'index_table': index_table,
        }
    )
