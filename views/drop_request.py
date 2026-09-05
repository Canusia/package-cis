"""
Drop Request Views
"""
import logging
from django.conf import settings
from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse, HttpResponse
from django.template.context_processors import csrf

from crispy_forms.utils import render_crispy_form

from cis.models.section import StudentDropRequest
from cis.models.student import Student
from cis.models.term import Term
from cis.models.course import Campus

from cis.utils import (
    registration_terms, active_term, YES_NO_OPTIONS, get_default_campus,
    can_edit_campus_registration,
    CIS_user_only,
    FACULTY_user_only,
    HSADMIN_user_only
)
from cis.menu import cis_menu, draw_menu
from cis.settings.registrations import RegistrationForm
from cis.forms.section import (
    EditStudentRegistration, AddNewStudentRegistrationForm,
    ProcessStudentDropRequest
)

from django.views.decorators.clickjacking import xframe_options_exempt

from ..serializers.registration import StudentDropRequestSerializer
logger = logging.getLogger(__name__)

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from rest_framework.decorators import api_view
from rest_framework.response import Response

from cis.views.eager import (
    eager_queryset,
    with_drop_request_related,
)


@eager_queryset(with_drop_request_related)
class StudentDropViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = StudentDropRequestSerializer
    permission_classes = [CIS_user_only|FACULTY_user_only|HSADMIN_user_only]    

    def get_queryset(self):
        term = self.request.GET.get('term', str(active_term().id)).strip()
        campus = self.request.GET.get('campus', '').strip()
        status = self.request.GET.get('status', '').strip()

        student = self.request.GET.get('student', '').strip()
        class_section = self.request.GET.get('class_section', '').strip()

        records = StudentDropRequest.objects.filter().all()

        if student:
            records = records.filter(student__id=student)

        if class_section:
            records = records.filter(registration__class_section__id=class_section)

        if status:
            records = records.filter(status=status)

        if term:
            records = records.filter(registration__class_section__term__id=term)

        # if campus:
        #     records = records.filter(registration__class_section__campus__id=campus)

        return records

def delete(request, record_id):
    record = get_object_or_404(StudentDropRequest, pk=record_id)
    registration = record.registration

    if can_edit_campus_registration(request.user, registration):
        record.delete()
        data = {
            'status':'success',
            'message':'Success removed request',
        }
    else:
        data = {
            'status':'error',
            'message':'You do not have permission to delete this request',
        }
    return JsonResponse(data)

@xframe_options_exempt
def detail(request, record_id):
    """
    Record details page
    """
    template = 'cis/drop_wd/detail.html'
    record = get_object_or_404(StudentDropRequest, pk=record_id)

    form = ProcessStudentDropRequest(record)

    if request.method == 'POST':
        form = ProcessStudentDropRequest(record, request.POST)

        if form.is_valid():
            record = form.save(record)

            messages.add_message(
                request,
                messages.SUCCESS,
                'Successfully updated request & class registration',
                'list-group-item-success') 
            return redirect('cis:drop_wd_req', record_id=record_id)

    student = Student.objects.get(
        pk=record.student.id
    )
    return render(
        request,
        template, {
            'form': form,
            'page_title': "Student Drop/WD Request",
            'record': record,
            'recommendation': record.registration.get_recommendation(),
            'registrations_url': f'/ce/api/registration?format=datatables&student={student.id}',
            'note_api_url': f'/ce/api/student-note/?student_id={student.id}&format=datatables',
            'student_signature': record.registration.get_student_signature(),
            'parent_consent': record.registration.get_parent_consent(),
            'student': student
        })

def index(request):
    '''
     search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'students', 'drop_wd_reqs')
    template = 'cis/drop_wd/index.html'

    return render(
        request,
        template, {
            'menu': menu,
            'page_title': 'Drop/WD Requests',
            'api_url': '/ce/api/drop_wd_req?format=datatables',
            'active_term': active_term(),
            'campus': Campus.objects.filter(
                code__startswith=settings.CAMPUS_CODE_PREFIX).all(),
            'terms': Term.objects.all(),
            'default_campus': get_default_campus(request.user),
            'registration_status': StudentDropRequest.STATUS_OPTIONS
        }
    )
