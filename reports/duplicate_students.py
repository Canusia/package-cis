import io
import csv
import datetime

from django import forms
from django.db.models import Count, Value
from django.db.models.functions import Concat, Lower, Trim
from django.urls import reverse_lazy
from django.utils.encoding import force_str
from django.core.files.base import ContentFile

from cis.backends.storage_backend import PrivateMediaStorage
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from cis.models.student import Student

# Group key: last|first, case- and whitespace-insensitive. Matching on name
# alone is deliberate. Date of birth is only collected in the second half of
# the application (complete_signup), so an abandoned account has none -- and
# those are precisely the accounts this report is used to hunt down. Requiring
# a DOB match would hide every duplicate that pairs a finished account with an
# abandoned one. DOB ships as a column instead, for the admin to eyeball.
_NAME_KEY = Concat(
    Lower(Trim('user__last_name')),
    Value('|'),
    Lower(Trim('user__first_name')),
)

# (header, accessor). Built explicitly rather than through cis.utils.get_field:
# that helper walks dotted paths with getattr and never calls what it finds, so
# 'user.has_usable_password' would serialise as "<bound method ...>".
_COLUMNS = [
    ('Canusia Id', lambda s: s.user.id),
    ('User ID', lambda s: s.user.psid or ''),
    ('First Name', lambda s: s.user.first_name),
    ('Last Name', lambda s: s.user.last_name),
    ('Middle Name', lambda s: s.user.middle_name or ''),
    ('Suffix', lambda s: s.user.suffix or ''),
    # preferred_name lives on Student, not CustomUser. The old report read it
    # off the user via get_field(), which swallows AttributeError and returns
    # '' -- so this column was silently blank in every export.
    ('Preferred Name', lambda s: s.preferred_name or ''),
    ('Email', lambda s: s.user.email),
    ('Date of Birth', lambda s: s.user.date_of_birth or ''),
    ('High School', lambda s: s.highschool.name if s.highschool_id else ''),
    ('Account Verified', lambda s: 'Yes' if s.account_verified else 'No'),
    # The orphan tell: an account nobody can log into and nobody can re-create.
    # has_login_password() rather than Django's has_usable_password(), which
    # answers True for the empty password these accounts carry.
    ('Has Password',
     lambda s: 'Yes' if s.user.has_login_password() else 'No'),
    ('Registrations', lambda s: s.n_reg),
    ('Last Login',
     lambda s: s.user.last_login.strftime('%m/%d/%Y') if s.user.last_login
     else ''),
]


class duplicate_students(forms.Form):


    roles = []
    request = None
    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.request = request

        self.helper = FormHelper()
        # self.helper.attrs = {'target':'_blank'}
        self.helper.form_method = 'POST'
        self.helper.add_input(Submit('submit', 'Generate Export'))

        # for cis users only show their campus
        if self.request:
            self.helper.form_action = reverse_lazy(
                'report:run_report', args=[request.GET.get('report_id')]
            )

    def get_result(self, data):
        """Students who share a first + last name with another student.

        Starts from Student, so the result is student-only by construction.
        The previous implementation self-joined cis_customuser -- the account
        table shared by every role -- with no join to cis_student and no group
        filter, so any instructor, faculty member or HS admin whose name
        collided was exported too. It also emitted one row of u1 per matching
        u2, inflating an N-way group to N*(N-1) rows.
        """
        base = Student.objects.annotate(
            ln=Lower(Trim('user__last_name')),
            fn=Lower(Trim('user__first_name')),
            name_key=_NAME_KEY,
        ).exclude(ln='').exclude(fn='')

        duplicate_keys = (
            base.values('name_key')
                .annotate(n=Count('id'))
                .filter(n__gt=1)
                .values_list('name_key', flat=True)
        )

        return (
            # Not list(): materializing every duplicate key into Python only to
            # ship it back as one large IN (...) is the pattern not_applied was
            # rewritten to avoid (views/student.py). Django turns the queryset
            # into a subquery.
            base.filter(name_key__in=duplicate_keys)
                .select_related('user', 'highschool')
                .annotate(n_reg=Count('studentregistration', distinct=True))
                .order_by('ln', 'fn', 'user__id')
        )

    def run(self, task, data):
        records = self.get_result(data)

        file_name = "potential-dup-student-export.csv"

        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=',')

        writer.writerow([header for header, _ in _COLUMNS])
        for record in records:
            writer.writerow([
                force_str(accessor(record)) for _, accessor in _COLUMNS
            ])

        now = datetime.datetime.now().strftime("%Y/%m")
        path = f"reports/{now}/" + str(task.id) + "/" + file_name
        media_storage = PrivateMediaStorage()

        path = media_storage.save(path, ContentFile(stream.getvalue().encode('utf-8')))
        path = media_storage.url(path)

        return path

    def run_report(self):
        ...
