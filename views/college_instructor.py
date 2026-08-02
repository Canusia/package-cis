from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.conf import settings

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse

from cis.models.course import Course
from cis.models.customuser import CustomUser
from cis.models.teacher import (
    Teacher, TeacherHighSchool, TeacherCourseCertificate
)
import importlib.util
if importlib.util.find_spec('future_sections.future_sections'):
    from future_sections.future_sections.models import FutureCourse, FutureSection
else:
    from future_sections.models import FutureCourse, FutureSection
from cis.models.section import ClassSection, SectionNumber
from cis.models.note import TeacherNote

from cis.forms.teacher import (
    TeacherForm, TeacherHighSchoolForm,
    TeacherCourseForm
)

from cis.menu import cis_menu, draw_menu

def index(request):
    '''
    Teacher search and index page for staff
    '''
    menu = draw_menu(cis_menu, 'faculty', 'college_instructors')

    template = 'cis/teachers/college_instructors.html'
    query = request.GET.get('q', '')
    page = request.GET.get('page', 1)
    order_by = request.GET.get('order_by', 'user__first_name').lower()
    order = request.GET.get('order', 'asc')

    valid_order_by_fields = [
        'user__first_name'
    ]
    if order_by not in valid_order_by_fields:
        order_by = 'user__first_name'

    valid_order = [
        'asc', 'desc'
    ]
    if order not in valid_order:
        order = 'asc'

    if not query:
        record_list = Teacher.objects.all().order_by(
            order_by if order == 'asc' else f"-{order_by}")
    else:
        qry = Q()
        qry.add(Q(user__first_name__icontains=query), Q.OR)
        qry.add(Q(user__last_name__icontains=query), Q.OR)
        qry.add(Q(user__psid__icontains=query), Q.OR)
        qry.add(Q(user__email__icontains=query), Q.OR)

        try:
            query = int(query)
            qry.add(Q(temp_id=query), Q.OR)
        except ValueError:
            pass

        record_list = Teacher.objects.filter(qry).order_by(
            order_by if order == 'asc' else f"-{order_by}")

    # Remove all teachers who are not teaching F2F sections
    record_list = record_list.exclude(
        pk__in=ClassSection.objects.filter(
            Q(section_number__section_type=SectionNumber.F2F)
        ).values_list('teacher__id', flat=True)
    )

    if request.GET.get('export') == 'excel':
        return Teacher.export_to_excel(record_list)

    search_help = """
        <ul class='ml-0 pl-3'>
        <li class=''>First Name</li>
        <li class=''>Last Name</li>
        <li class=''>PS ID</li>
        <li class=''>UMN Email</li>
        </ul>
        """
    paginator = Paginator(record_list, settings.MY_CE.get('paginator_per_page', 30))
    try:
        records = paginator.page(page)
    except PageNotAnInteger:
        records = paginator.page(1)
    except EmptyPage:
        records = paginator.page(paginator.num_pages)

    return render(
        request,
        template, {
            'menu': menu,
            'count': paginator.count,
            'search_help': search_help,
            'records':records,
            'q': query,
            'order_by': order_by,
            'order': order})

from django.views.decorators.clickjacking import xframe_options_exempt
@xframe_options_exempt
def detail(request, record_id):
    '''
    Record details page
    '''
    template = 'cis/teachers/college_instructor.html'
    record = get_object_or_404(Teacher, pk=record_id)

    if request.method == 'POST':
        form = TeacherForm(request.POST)

        if form.is_valid():
            try:
                user = CustomUser.objects.get(pk=record.user.id)

                user.first_name = form.cleaned_data['first_name']
                user.last_name = form.cleaned_data['last_name']
                user.email = form.cleaned_data['email']
                user.username = form.cleaned_data['username'].lower()
                user.alt_email = form.cleaned_data['alt_email']
                user.secondary_email = form.cleaned_data['secondary_email']
                user.primary_phone = form.cleaned_data['primary_phone']
                user.secondary_phone = form.cleaned_data['secondary_phone']
                user.alt_phone = form.cleaned_data['alt_phone']
                user.psid = form.cleaned_data['psid']

                user.address1 = form.cleaned_data['address1']
                user.city = form.cleaned_data['city']
                user.state = form.cleaned_data['state']
                user.postal_code = form.cleaned_data['postal_code']

                user.save()

                messages.add_message(
                    request,
                    messages.SUCCESS,
                    'Successfully updated record',
                    'list-group-item-success') 
                return redirect('cis:instructor', record_id=record_id)
            except IntegrityError:
                form._errors['email'] = ['An account with this email/username already exists.']
    else:
        form = TeacherForm(initial={
            'first_name':record.user.first_name,
            'last_name':record.user.last_name,
            'email':record.user.email,
            'username':record.user.username,
            'alt_email':record.user.alt_email,
            'secondary_email':record.user.secondary_email,
            'primary_phone': record.user.primary_phone,
            'secondary_phone': record.user.secondary_phone,
            'alt_phone': record.user.alt_phone,
            'psid': record.user.psid,
            'address1': record.user.address1,
            'city': record.user.city,
            'state': record.user.state,
            'postal_code': record.user.postal_code,
        })

    courses = TeacherCourseCertificate.objects.filter(teacher_highschool__teacher=record.id)
    sections = ClassSection.objects.filter(teacher=record.id)
    notes = TeacherNote.objects.filter(teacher=record.id).order_by("-createdon")

    return render(
        request,
        template, {
            'form': form,
            'page_title': "Instructor Details",
            'labels': {
                'all_items': 'All Instructors'
            },
            'urls': {
                'add_new': 'cis:instructor_add_new',
                'all_items': 'cis:college_instructors'
            },
            'menu': draw_menu(cis_menu, 'faculty', 'college_instructors'),
            'record': record,
            'courses': courses,
            'sections': sections,
            'notes': notes
        })
