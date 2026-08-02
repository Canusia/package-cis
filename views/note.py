from django.db import IntegrityError
from django.db.models import Q
from django.contrib import messages
from django.conf import settings

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.urls import reverse

from cis.models.note import StudentNote
from cis.menu import cis_menu, draw_menu
from cis.forms.note import (
    NoteForm, StudentNoteForm,
    StudentNoteReplyForm,
    ClassSectionNoteForm,
    TeacherApplicationNoteForm,
    TeacherNoteForm,
    VisitReportNoteForm,
    StudentPlanNoteForm,
    EventNoteForm
)

from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from cis.utils import user_has_cis_role

def delete_note(request):
    pass


def add_new_note(request, add_to):
    '''
    Add new note
    '''
    ajax = request.GET.get('ajax', None)
    parent = request.GET.get('parent')
    base_template = 'cis/logged-base.html' if not ajax else 'cis/ajax-base.html'
    template = 'cis/notes/manage_note.html'

    if request.method == 'POST':
        if request.POST.get('model') == 'studentnote':
            form = StudentNoteForm(request.POST, request.FILES)
        if request.POST.get('model') == 'eventnote':
            form = EventNoteForm(request.POST)
        elif request.POST.get('model') == 'teachernote':
            form = TeacherNoteForm(request.POST, request.FILES)
        elif request.POST.get('model') == 'student_replynote':
            form = StudentNoteReplyForm(request.POST, request.FILES)
        elif request.POST.get('model') == 'classsectionnote':
            form = ClassSectionNoteForm(request.POST)
        elif request.POST.get('model') == 'teacherapplicationnote':
            form = TeacherApplicationNoteForm(request.POST)
        elif request.POST.get('model') == 'studentplannote':
            form = StudentPlanNoteForm(request, request.POST)
        elif request.POST.get('model') == 'visitreportnote':
            form = VisitReportNoteForm(request.POST)
        else:
            form = NoteForm(request.POST)

        context = {
            'form': form,
            'base_template': base_template,
        }
        if form.is_valid():
            try:
                note = None
                if form.cleaned_data['model'] == f"teacherapplicationnote":
                    from cis.models.note import TeacherApplicationNote as note_model
                    note = note_model.add_note(request, form)
                
                elif form.cleaned_data['model'] == f"visitreportnote":
                    from cis.models.note import ClassVisitReportNote as note_model
                    note = note_model.add_note(request, form)
                
                elif form.cleaned_data['model'] == f"coursenote":
                    from cis.models.note import CourseNote as note_model
                    note = note_model.add_note(request, form)

                elif form.cleaned_data['model'] == f"classsectionnote":
                    from cis.models.note import ClassSectionNote
                    note = ClassSectionNote.add_note(request, form)
                
                elif form.cleaned_data['model'] == f"eventnote":
                    from cis.models.note import EventNote
                    note = EventNote.add_note(request, form)

                elif form.cleaned_data['model'] == f"highschoolnote":
                    from cis.models.note import HighSchoolNote
                    note = HighSchoolNote.add_note(request, form)

                elif form.cleaned_data['model'] == f"teachernote":
                    from cis.models.note import TeacherNote
                    note = TeacherNote.add_note(request, form)

                elif form.cleaned_data['model'] == f"hsadminnote":
                    if not user_has_cis_role(request.user):
                        return JsonResponse({
                            'status': 'error',
                            'message': 'You are not authorized to perform this action.',
                        }, status=403)
                    from cis.models.note import HSAdministratorNote
                    note = HSAdministratorNote.add_note(request, form)

                elif form.cleaned_data['model'] == f"ticketnote":
                    from support_ticket.models.ticket import TicketNote
                    note = TicketNote.add_note(request, form)

                elif form.cleaned_data['model'] == f"studentnote" or form.cleaned_data['model'] == 'student_replynote':
                    from cis.models.note import StudentNote
                    note = StudentNote.add_note(request, form)

                if note:
                    if form.cleaned_data['ajax'] == '1':
                        data = {
                            'status':'success',
                            'message':'Successfully added note',
                            'action': 'reload'
                        }
                        return JsonResponse(data)
                else:
                    if form.cleaned_data['ajax'] == '1':
                        data = {
                            'status':'success',
                            'message':'There was an error while adding note'
                        }
                        return JsonResponse(data)

            except IntegrityError as exception:
                if form.cleaned_data['ajax'] == '1':
                    data = {
                        'status':'error',
                        'message':'Looks like a duplicate entry' + str(exception)
                    }
                    return JsonResponse(data)
                form._errors['note'] = ['Unable to add note - ' + str(exception)]
        else:
            data = {
                'status':'error',
                'message':'There was an error while adding note.<br>'+str(form.errors['note'])
            }
            return JsonResponse(data)

    else:
        initial = {
            'model': f'{add_to}note',
            'ajax': 1,
            'add_to': request.GET.get('parent'),
            'id': -1
        }
        if add_to == 'classsection':
            form = ClassSectionNoteForm(initial=initial)
        if add_to == 'eventsection':
            form = EventNoteForm(initial=initial)
        elif add_to == 'student':
            form = StudentNoteForm(initial=initial)
        elif add_to == 'teacher':
            form = TeacherNoteForm(initial=initial)
        elif add_to == 'student_reply':
            from cis.models.note import StudentNote

            initial['reply_to'] = request.GET.get('parent')
            note = StudentNote.objects.get(
                pk=request.GET.get('parent')
            )
            if note.parent:
                initial['reply_to'] = str(note.parent)

            initial['add_to'] = str(note.student.id)
            form = StudentNoteReplyForm(initial=initial)            
        else:
            form = NoteForm(initial=initial)
        
        if add_to == "visitreport":
            from class_visit.models import VisitReport

            record = VisitReport.objects.get(pk=parent)

            form = VisitReportNoteForm(initial=initial)
            context = {
                'title': f"Add Note to Report",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
            }

        if add_to == "teacherapplication":
            from cis.models.teacher_applicant import TeacherApplication

            try:
                record = TeacherApplication.objects.get(pk=parent)
            except TeacherApplication.DoesNotExist:
                note = TeacherApplicationNote.objects.get(pk=parent)

                initial['reply_to'] = str(note.parent) if note.parent else str(note.id)
                initial['add_to'] = str(note.teacher_application.id)
                record = note.teacher_application

            form = TeacherApplicationNoteForm(initial=initial)
            context = {
                'title': f"Add Note to {record.user.first_name} {record.user.last_name}",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
            }

        if add_to == "ticket":
            from support_ticket.models.ticket import Ticket
            record = Ticket.objects.get(pk=parent)
            context = {
                'title': f"Add Update",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                #'menu': draw_menu(cis_menu, 'highschools', 'all_highschools')
            }

        if add_to == "classsection":
            from cis.models.section import ClassSection
            record = ClassSection.objects.get(pk=parent)
            context = {
                'title': f"Add Note to {record.class_number} / {record.section_number}",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                'menu': draw_menu(cis_menu, 'highschools', 'all_highschools')
            }

        if add_to == "event":
            context = {
                'title': f"Add Note",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                # 'menu': draw_menu(cis_menu, 'highschools', 'all_highschools')
            }

        if add_to == "highschool":
            from cis.models.highschool import HighSchool
            record = HighSchool.objects.get(pk=parent)
            context = {
                'title': f"Add Note to {record.name}",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                'menu': draw_menu(cis_menu, 'highschools', 'all_highschools')
            }

        if add_to == "hsadmin":
            if not user_has_cis_role(request.user):
                return JsonResponse({
                    'status': 'error',
                    'message': 'You are not authorized to perform this action.',
                }, status=403)
            from cis.models.highschool_administrator import HSAdministrator
            record = HSAdministrator.objects.get(pk=parent)
            context = {
                'title': f"Add Note to {record.user.first_name} {record.user.last_name}",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                'menu': draw_menu(cis_menu, 'highschools', 'hsadmin')
            }

        if add_to == "teacher":
            from cis.models.teacher import Teacher
            record = Teacher.objects.get(pk=parent)
            context = {
                'title': f"Add Note to {record.user.first_name} {record.user.last_name}",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                'menu': draw_menu(cis_menu, 'highschools', 'instructors')
            }
        
        if add_to == "course":
            from cis.models.course import Course
            record = Course.objects.get(pk=parent)
            context = {
                'title': f"Add Note to {record}",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                # 'menu': draw_menu(cis_menu, 'highschools', 'instructors')
            }

        if add_to == "student":
            from cis.models.student import Student
            record = Student.objects.get(pk=parent)
            form = StudentNoteForm(initial=initial)

            context = {
                'title': f"Add Note to {record.user.first_name} {record.user.last_name}'s Record",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
                'menu': draw_menu(cis_menu, 'highschools', 'instructors')
            }

        if add_to == "studentplan":
            from degree_pathway.models import StudentPlan
            record = StudentPlan.objects.get(pk=parent)
            form = StudentPlanNoteForm(request, initial=initial)

            context = {
                'title': f"Add Note to {record.student}'s Academic Plan",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template
            }

        if add_to == "student_reply":
            from cis.models.student import Student
            from cis.models.note import StudentNote

            note = StudentNote.objects.get(
                pk=request.GET.get('parent')
            )
            record = Student.objects.get(pk=note.student.id)

            form = StudentNoteReplyForm(initial=initial)

            context = {
                'title': f"Reply to {record.user.first_name} {record.user.last_name}'s Note",
                'form': form,
                'ajax': ajax,
                'model': f'{add_to}note',
                'base_template': base_template,
            }

    return render(request, template, context)
