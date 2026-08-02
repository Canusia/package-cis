import csv
import io

from django.db import IntegrityError
from django.db.models import Q, Count
from django.contrib import messages
from django.conf import settings

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.urls import reverse

from cis.models.teacher import TeacherHighSchool
from cis.campus_gate import scope_by_course_cert_campus
from cis.models.highschool import (
    HighSchool, HighSchoolCollegeAdvisor, HighSchoolTranscript
)
from cis.models.term import Term
from cis.models.course import Course
from django.utils.safestring import mark_safe

from cis.services.table_configs import get_table_config
build_sections_table_config = get_table_config('sections_table').build_config
build_instructors_table_config = get_table_config('instructors_table').build_config
build_highschools_table_config = get_table_config('highschools_table').build_config

# Bulk buttons on both index tabs. Dispatched by do_bulk_action below.
HIGHSCHOOL_BULK_ACTIONS = {
    'set_hs_type': {
        'label': 'Set School Type',
        'icon': 'fas fa-tags',
        'btn_class': 'btn-primary',
        'confirm': None,
    },
}

from myce.component_registry.highschool import highschool_tabs, highschool_actions

import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureSection, FutureCourse
else:
    from future_sections.models import FutureSection, FutureCourse

from cis.utils import registration_terms, user_has_cis_role, can_edit_highschool
from cis.models.section import SectionNumber, ClassSection, StudentRegistration
from cis.models.note import HighSchoolNote
from cis.models.highschool_administrator import HSAdministrator, HSAdministratorPosition
from cis.forms.highschool import HSModelForm, HSCollegeAdvisorForm, HighSchoolStatusUpdateForm, HighSchoolUploadForm

from cis.forms.section import AddNewHighSchoolClassOfferingForm
from cis.forms.highschool import HSTranscriptUploadForm

from cis.menu import cis_menu, draw_menu

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view
from rest_framework.response import Response

from ..serializers.highschool import (
    HighSchoolSerializer, HighSchoolTeacherSerializer,
    HighSchoolAdministratorSerializer,
    HighSchoolTranscriptSerializer
)

from ..serializers.note import HighSchoolNoteSerializer

from cis.utils import CIS_user_only, active_term

class HighSchoolViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        status = self.request.GET.get('status')

        if status:
            records = HighSchool.objects.filter(
                status=status
            )
        else:
            records = HighSchool.objects.all()

        return records

class HighSchoolServedByCampusViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        campus_id = self.request.GET.get('campus_id', '').strip()
        term_id = self.request.GET.get('term_id', '').strip()

        if not term_id:
            term_id = active_term().id

        highschool_ids = StudentRegistration.objects.filter(
            class_section__campus__id=campus_id,
            class_section__term__id=term_id
        ).distinct(
            'student__highschool__id'
        ).values_list(
            'student__highschool_id', flat=True
        )

        # print(highschool_ids)
        records = HighSchool.objects.filter(
            id__in=highschool_ids
        )
        return records


class HighSchoolTranscriptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolTranscriptSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        highschool_id = self.request.GET.get('highschool_id', '').strip()

        try:
            return HighSchoolTranscript.objects.filter(
                highschool__id=highschool_id
            ).order_by('-uploaded_on')
        except:
            return HighSchoolTranscript.objects.none()
        
class HighSchoolTeacherViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolTeacherSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        highschool_id = self.request.GET.get('highschool_id')
        campus = self.request.GET.get('campus', '').strip()

        if highschool_id:
            highschool = HighSchool.objects.get(pk=highschool_id)
            return highschool.teachers_in_highschool(return_type='teacherhighschool')

        # Campus gate (#by_highschool tab): scope to teacher-highschools whose
        # teacher is certified for a course at a processable campus; those with
        # no course certs are universal. The dropdown narrows to one campus.
        records = TeacherHighSchool.objects.all()
        return scope_by_course_cert_campus(
            records, self.request.user, cert_path='teachercoursecertificate',
            selected_campus=campus or None)

class HighSchoolAdministratorViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolAdministratorSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        highschool_id = self.request.GET.get('highschool_id')
        try:
            highschool = HighSchool.objects.get(pk=highschool_id)

            return highschool.administrators_in_highschool(
                return_type='hsadministratorposition')
        except:
            return HSAdministratorPosition.objects.none()

class HighSchoolNoteViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HighSchoolNoteSerializer
    permission_classes = [CIS_user_only]

    def get_queryset(self):
        highschool_id = self.request.GET.get('highschool_id')
        try:
            highschool = HighSchool.objects.get(pk=highschool_id)

            return HighSchoolNote.objects.filter(
                highschool=highschool)
        except:
            return HighSchoolNote.objects.none()

def index(request):
    '''
    High School search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'highschools', 'all_highschools')
    template = 'cis/highschools/index.html'

    # Get terms that have class sections at high schools
    terms = Term.objects.filter(
        classsection__highschool__isnull=False
    ).distinct().order_by('-code', '-label')

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'High Schools',
            'api_url': '/ce/api/highschool?format=datatables',
            'google_maps_api_key': getattr(settings, 'GOOGLE_MAPS_API_KEY', ''),
            'terms': terms,
            'registration_statuses': StudentRegistration.STATUS_OPTIONS,
            'highschools_table_active': build_highschools_table_config(
                variant='highschools_active',
                api_url='/ce/api/highschool?format=datatables&status=Active',
                details_prefix='/ce/highschool/',
                bulk_actions=HIGHSCHOOL_BULK_ACTIONS,
                bulk_actions_url=str(reverse('cis:highschool_bulk_actions')),
            ),
            'highschools_table_all': build_highschools_table_config(
                variant='highschools_all',
                api_url='/ce/api/highschool?format=datatables',
                details_prefix='/ce/highschool/',
                bulk_actions=HIGHSCHOOL_BULK_ACTIONS,
                bulk_actions_url=str(reverse('cis:highschool_bulk_actions')),
            ),
            'urls': {
                'details_prefix': '/ce/highschool/',
                'add_new': 'cis:hs_add_new'
            }
        }
    )


def highschool_map_data(request):
    """Return high school locations as JSON for map display."""
    term_ids = request.GET.getlist('term_ids')
    course_ids = request.GET.getlist('course_ids')
    statuses = request.GET.getlist('statuses')

    # Default to all statuses if none specified
    if not statuses:
        statuses = [status[0] for status in StudentRegistration.STATUS_OPTIONS]

    # Base query - active schools with coordinates
    schools = HighSchool.objects.select_related('district').filter(
        status__iexact='active',
        latitude__isnull=False,
        longitude__isnull=False
    )

    # Filter by terms if provided
    if term_ids:
        hs_ids_in_terms = ClassSection.objects.filter(
            term_id__in=term_ids,
            highschool__isnull=False
        ).values_list('highschool_id', flat=True).distinct()
        schools = schools.filter(id__in=hs_ids_in_terms)

    # Filter by courses if provided
    if course_ids:
        hs_ids_with_courses = ClassSection.objects.filter(
            term_id__in=term_ids,
            course_id__in=course_ids,
            highschool__isnull=False
        ).values_list('highschool_id', flat=True).distinct()
        schools = schools.filter(id__in=hs_ids_with_courses)

    school_list = []
    for school in schools:
        # Build course statistics for this school
        section_filter = {'highschool': school}
        if term_ids:
            section_filter['term_id__in'] = term_ids
        if course_ids:
            section_filter['course_id__in'] = course_ids

        # Get course stats: course name, section count, student count
        # Filter student count by selected registration statuses
        course_stats = ClassSection.objects.filter(
            **section_filter
        ).values(
            'course__name'
        ).annotate(
            section_count=Count('id'),
            student_count=Count(
                'studentregistration',
                filter=Q(studentregistration__status__in=statuses)
            )
        ).order_by('course__name')

        school_list.append({
            'id': str(school.id),
            'name': school.name,
            'address1': school.address1,
            'city': school.city,
            'state': school.state,
            'postal_code': school.postal_code,
            'latitude': school.latitude,
            'longitude': school.longitude,
            'district': school.district.name if school.district else 'No District',
            'courses': [
                {
                    'name': cs['course__name'],
                    'sections': cs['section_count'],
                    'students': cs['student_count']
                } for cs in course_stats
            ]
        })

    return JsonResponse({'schools': school_list})


def highschool_map_courses(request):
    """Return courses that have class sections in given terms at high schools."""
    term_ids = request.GET.getlist('term_ids')

    if not term_ids:
        return JsonResponse({'courses': []})

    course_ids = ClassSection.objects.filter(
        term_id__in=term_ids,
        highschool__isnull=False
    ).values_list('course_id', flat=True).distinct()

    courses = Course.objects.filter(id__in=course_ids).order_by('name')

    return JsonResponse({
        'courses': [{'id': str(c.id), 'name': c.name} for c in courses]
    })

def ajax_search(request):
    search = request.GET.get('q','')
    records = HighSchool.objects.filter(
        name__contains=search
    )

    result = {'items':[]}
    if records:
        for r in records:
            r = {
                'html_url': reverse('cis:hs_detail', kwargs={'record_id':r.id}),
                'name': r.name
            }
            result['items'].append(r)

    return JsonResponse(result)

def import_from_file(request):
    """Handle CSV file upload for high school import."""
    from cis.services.importers import HighSchoolRow

    form = HighSchoolUploadForm(request.POST, request.FILES)

    if form.is_valid():
        decoded_file = request.FILES.get('file').read().decode('utf-8-sig', errors='ignore')
        reader = csv.DictReader(io.StringIO(decoded_file))

        result = HighSchool.import_from_csv(reader)
        if result['status'] == 'success':
            if not result['records']:
                messages.add_message(
                    request,
                    messages.WARNING,
                    'The uploaded file contained no data rows.',
                    'list-group-item-warning')
                return redirect('cis:hs_add_new')

            file_name = "highschool_import_results.csv"
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
        return redirect('cis:hs_add_new')

def download_highschool_template(request):
    """Download a blank CSV template with the correct headers for high school import."""
    from cis.services.importers import HighSchoolRow

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="highschool_import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(HighSchoolRow.csv_headers())
    return response

def add_new(request):
    '''
    Add new High school page
    '''
    from cis.services.importers import HighSchoolRow

    template = 'cis/highschools/add-new.html'
    upload_form = HighSchoolUploadForm()

    if request.method == 'POST':
        if request.POST.get('upload_file') == "Import High Schools":
            return import_from_file(request)

        form = HSModelForm(request.POST)

        if form.is_valid():
            record = form.save(commit=False)
            record.save()

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully added record',
                'list-group-item-success'
            )
            return redirect('cis:highschools')
    else:
        form = HSModelForm()

    return render(
        request,
        template, {
            'form': form,
            'upload_form': upload_form,
            'schema_fields': HighSchoolRow.field_definitions(),
            'required_header': HighSchoolRow.csv_headers(),
            'menu': draw_menu(cis_menu, 'highschools', 'all_highschools')
        })

def tab(request, record_id, tab_slug):
    """Render a single High School detail-page tab fragment (lazy AJAX)."""
    record = get_object_or_404(HighSchool, pk=record_id)
    return highschool_tabs.render_tab(request, record, tab_slug)


from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    High school details page
    '''
    template = 'cis/highschools/details.html'
    record = get_object_or_404(HighSchool, pk=record_id)

    hs_transcript_upload_form = HSTranscriptUploadForm()

    from cis.forms.highschool import MigrateForm
    migration_form = MigrateForm(record=record)

    form = HSModelForm(instance=record)
    if request.method == 'POST':

        if request.POST.get('action') == 'migrate_highschool':
            migration_form = MigrateForm(
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

        elif request.POST.get('action', '') == 'upload_transcript':
            hs_transcript_upload_form = HSTranscriptUploadForm(
                request.POST, request.FILES
            )

            if hs_transcript_upload_form.is_valid():
                transcript = hs_transcript_upload_form.save(commit=False)
                transcript.highschool = record
                transcript.uploaded_by = request.user
                transcript.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully uploaded file',
                    'list-group-item-success') 
                return redirect('cis:hs_detail', record_id=record_id)                
        else:            
            form = HSModelForm(request.POST, instance=record)
            if can_edit_highschool(request.user):
                if form.is_valid():
                    record = form.save(commit=False)
                    record.save()

                    messages.add_message(
                        request,
                        messages.SUCCESS,
                        'Successfully updated record',
                        'list-group-item-success') 
                    return redirect('cis:hs_detail', record_id=record_id)
            else:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'You do not have permission to edit high school information',
                    'list-group-item-warning'
                )
    
    return render(
        request,
        template, {
            'menu': draw_menu(cis_menu, 'highschools', 'all_highschools'),
            'record': record,
            'detail_tabs': highschool_tabs.for_record(
                request, record,
                url_for=lambda slug: reverse('cis:highschool_tab', args=[record.id, slug]),
            ),
            'detail_actions': highschool_actions.for_scope('detail', request.user),
        })

def delete(request, record_id):
    record = get_object_or_404(HighSchool, pk=record_id)

    try:
        record.delete()
    
        data = {
            'status':'success',
            'message':'Success removed record',
        }   
    except Exception as e:
        data = {
            "status": 'warning',
            'message': str(e)
        }

    return JsonResponse(data)

def download_transcript(request, record_id):
    file = get_object_or_404(
        HighSchoolTranscript,
        pk=record_id
    )

    from cis.backends.storage_backend import PrivateMediaStorage
    from django.http import FileResponse

    media_storage = PrivateMediaStorage()
    response = FileResponse(
        media_storage.open(str(file.media), 'rb'),
        content_type='application/force-download'
    )

    response['Content-Disposition'] = f'attachment; filename="{file.file_name}"'
    return response

def add_new_college_advisor(request):
    '''
    Add new highschool college advisor
    '''
    # PT-21: only CE (CIS) staff may view or modify HighSchoolCollegeAdvisor
    # records. This handler is reached via the add_new dispatcher
    # (model=highschoolcollegeadvisor) from BOTH /ce/add_new_ajax/ (which is
    # NOT URL-gated to CE in this repo) and /highschool_admin/ajax/ (gated to
    # highschool_admin, which delegates to the same dispatcher). So this
    # per-method guard is the sole authorization check for the operation.
    if not user_has_cis_role(request.user):
        return JsonResponse({
            'status': 'error',
            'message': 'You are not authorized to perform this action.',
        }, status=403)

    ajax = request.GET.get('ajax', None)
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/highschools/manage_college_advisor.html'

    if request.method == 'POST':
        form = HSCollegeAdvisorForm(request.POST)

        if form.is_valid():
            try:
                highschool = form.cleaned_data['highschool']
                advisor = form.cleaned_data['advisor']
                status = form.cleaned_data['status']

                if form.cleaned_data['id'] != '-1':
                    record = HighSchoolCollegeAdvisor.objects.get(
                        pk=form.cleaned_data['id'])
                else:
                    record = HighSchoolCollegeAdvisor()
                
                record.highschool = highschool
                record.advisor = advisor
                record.status = status

                record.save()

                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'success',
                        'message':'Successfully saved record',
                        'new_record_id':record.id,
                        'action': 'reload'
                    }
                    return JsonResponse(data)

            except IntegrityError:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Looks like a duplicate entry'
                    }
                    return JsonResponse(data)
                form._errors['highschool'] = ['The advisor already exists for this high school']
    else:
        initial = {
            'highschool':request.GET.get('parent'),
            'id': '-1',
            'ajax': ajax
        }

        if request.GET.get('id', '-1') != '-1':
            record = HighSchoolCollegeAdvisor.objects.get(
                pk=request.GET.get('id'))
            initial['id'] = record.id
            initial['highschool'] = record.highschool
            initial['advisor'] = record.advisor

        highschool = get_object_or_404(HighSchool, pk=request.GET.get('parent'))
        form = HSCollegeAdvisorForm(initial=initial)

    return render(
        request,
        template, {
            'form': form,
            'ajax': ajax,
            'highschool': highschool,
            'base_template': base_template,
            'menu': draw_menu(cis_menu, 'highschools', 'instructors')
        })

def do_bulk_action(request):
    action = request.GET.get('action')

    if request.method == 'POST':
        action = request.POST.get('action')
        
    if action == 'change_status':
        return manage_status(request)

    if action == 'set_hs_type':
        return set_hs_type(request)

    data = {
        'status': 'success',
        'message': 'invalid action passed'
    }
    return JsonResponse(data)


def set_hs_type(request):
    """Set School Type on every selected high school.

    Genuinely multi-record, unlike manage_status above (which is single-record
    despite living behind do_bulk_action): ActionRegistry.doBulkAction posts
    ids[] for every selected row.

    Replaces each school's existing type set rather than adding to it — the
    modal says so.
    """
    from cis.services.tenant_services import get_tenant_service
    types = get_tenant_service('highschool_types')

    ids = request.POST.getlist('ids[]')
    if not ids:
        return JsonResponse({
            'status': 'error',
            'message': 'No high schools were selected.',
        }, status=400)

    # ActionRegistry POSTs for both steps, so the modal form carries apply=1 to
    # distinguish "show me the form" from "apply it".
    if request.POST.get('apply') != '1':
        html = render_to_string('cis/highschools/set_hs_type.html', {
            'title': 'Set School Type',
            'ids': ids,
            'choices': types.choices(),
            'count': len(ids),
            'form_action': str(reverse('cis:highschool_bulk_actions')),
        }, request=request)
        return JsonResponse({'outcome': 'modal', 'html': html})

    selected = request.POST.getlist('hs_type')
    unknown = [code for code in selected if code not in types.codes()]
    if unknown:
        return JsonResponse({
            'status': 'error',
            'message': 'Unknown School Type: %s' % ', '.join(unknown),
        }, status=400)

    updated = 0
    for record in HighSchool.objects.filter(pk__in=ids):
        record.hs_type = selected
        record.save()
        updated += 1

    label = ', '.join(types.labels(selected)) or 'no type'
    return JsonResponse({
        'outcome': 'call',
        'fn': 'reloadHighschoolTables',
        'args': {
            'title': 'School Type updated',
            'message': 'Set %s on %d high school(s).' % (label, updated),
        },
    })


def manage_status(request):
    template = 'cis/highschools/update_status.html'

    if request.method == 'POST':

        record_id = request.POST.get('record_id')
        record = get_object_or_404(
            HighSchool,
            pk=record_id
        )

        form = HighSchoolStatusUpdateForm(record=record, data=request.POST)
        if form.is_valid():
            status = form.save(request, record)

            data = {
                'status':'success',
                'message':'Successfully updated record',
                'action': 'reload_page'
            }
            return JsonResponse(data)
        else:
            data = {
                'status':'error',
                'message':'Please correct the errors and try again.',
                'errors': form.errors.as_json()
            }
        return JsonResponse(data, status=400)

    record_id = request.GET.get('record_id')
    record = get_object_or_404(
        HighSchool,
        pk=record_id
    )

    form = HighSchoolStatusUpdateForm(record)
    context = {
        'title': 'Change High School Status',
        'form': form,
        'form_action': str(reverse('cis:highschool_bulk_actions'))
    }
    
    return render(request, template, context)

class HighSchoolHistoryViewSet(viewsets.ViewSet):
    permission_classes = [CIS_user_only]

    def list(self, request):
        from ..serializers.history import HistorySerializer
        highschool_id = request.GET.get('highschool_id')
        try:
            HighSchool.objects.get(pk=highschool_id)
        except HighSchool.DoesNotExist:
            return Response({'data': []})

        history = HighSchool.history.filter(id=highschool_id).order_by('-history_date')
        serializer = HistorySerializer(history, many=True)
        return Response({'data': serializer.data})
