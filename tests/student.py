import io

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.conf import settings

from django.core.mail import send_mail
from django.test import override_settings

from cis.models.student import Student
from cis.forms.student import StudentForm

class Student(TestCase):
    
    def init_groups(self):
        s = getattr(settings, "MY_CE")
        for group in s['roles'].keys():
            g = Group(name=group)
            g.save()
            
    def test_student_form(self):
        student_data = {
            'first_name': 'Avi',
            'last_name': 'Kadaji',
            'date_of_birth': '10/20/2010',
            'ssn': '123-12-1234',
            'graduation_year': '2010',
            'email': 'kadaji@gmail1.com',
            'confirm_email': 'kadaji@gmail1.com',
            'password': 'kryGkin9318!',
            'confirm_password': 'kryGkin9318!',
            'gender': 'm',
            'cell_phone': '1231231234',
            'parent_first_name': 'Parent',
            'parent_last_name': 'Last Name',
            'mailing_address': '311 W Seneca St',
            'address_2': '26 E',
            'city': 'Manlius',
            'state': 'NY',
            'zip_code': '13104',
            'confirm_term': '1'
        }
        
        form = StudentForm(
            data=student_data
        )
        
        if form.is_valid():
            print(form.cleaned_data)
        else:
            print(form.errors)