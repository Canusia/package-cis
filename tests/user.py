import io

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.conf import settings

from django.core.mail import send_mail
from django.test import override_settings

from cis.models.teacher import Teacher

class User(TestCase):
    
    def init_groups(self):
        s = getattr(settings, "MY_CE")
        for group in s['roles'].keys():
            g = Group(name=group)
            g.save()
            
    def test_user_is_created(self):
        user_model = get_user_model()
        user = user_model.objects.create(username='kadaji', email='kadaji@gmail.com')

        #self.assertEqual(user.id, 1)

    def test_user_is_created_no_role(self):
        user_model = get_user_model()
        user = user_model.objects.create(username='kadaji', email='kadaji@gmail.com')

        self.assertEqual(len(user.groups.all()), 0)


    def test_user_get_roles(self):        
        self.init_groups()
        self.assertEqual(len(Group.objects.all()), len(getattr(settings, "MY_CE")['roles'].keys()))

        user_model = get_user_model()
        user = user_model.objects.create(username='kadaji', email='kadaji@gmail.com')

        g = Group.objects.get(name='applicant')
        g.user_set.add(user)

        self.assertEqual(len(user.groups.all()), 1)

    def test_email(self):
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import get_template
        from django.template import Context, Template
        
        text_body = 'This is a test'        
        template = get_template('cis/email.html')
        html_body = template.render({
            'message': text_body
        })
        to = ['kadaji@gmail.com']
        subject = 'Testing'

        email = EmailMultiAlternatives(subject, text_body)
        email.to = to
        email.attach_alternative(html_body, 'text/html')
        
        send_email_result = email.send()
        self.assertEqual(send_email_result, 1)

    # @override_settings(
    #     EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend')
    # def test_mass_email(self):
    #     from django.core.mail import send_mass_mail

    #     email = [(
    #         'Test SUbject - Mass Mail',
    #         'Test Message',
    #         'mycis@umn.edu',
    #         ['kadaji@gmail.com']
    #     )]
    #     send_email_result = send_mass_mail(email)
    #     self.assertEqual(send_email_result, 1)

