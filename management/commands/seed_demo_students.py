"""
Seed a demo student population for testing the onboarding tabs.

Creates three cohorts of 10 students each for the active term:
  - pending email verification (account_verified=False)
  - verified but missing FERPA
  - verified AND FERPA complete

Records go through the real `StudentVerifyEmailForm` and `StudentProfileForm`
save paths (validation is bypassed by setting `cleaned_data` directly) so all
the fields those forms populate are present.

Usage:
    docker exec -w /app/webapp django_web_ewu \\
        python manage.py seed_demo_students [--prefix demo] [--highschool "Name"]
"""
import datetime
import random
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction

from cis.forms.student import StudentVerifyEmailForm
from cis.forms.student_profile import StudentProfileForm
from cis.models.highschool import HighSchool
from cis.models.student import Student
from cis.utils import active_term

from student_onboarding.signals import onboarding_event
from student_onboarding import events as oe


FIRST_NAMES = [
    'Alex', 'Blair', 'Casey', 'Drew', 'Ellis', 'Finley', 'Gray', 'Harper',
    'Indigo', 'Jules', 'Kai', 'Logan', 'Morgan', 'Noel', 'Parker', 'Quinn',
    'River', 'Sage', 'Taylor', 'Val', 'Winter', 'Xan', 'Yael', 'Zion',
    'Avery', 'Brook', 'Cameron', 'Dakota', 'Emery', 'Frankie',
]
LAST_NAMES = [
    'Abbot', 'Brooks', 'Carver', 'Doyle', 'Ellis', 'Fox', 'Grant', 'Hale',
    'Irwin', 'James', 'Knox', 'Lane', 'Mercer', 'North', 'Oliver', 'Pratt',
    'Quinn', 'Reed', 'Stone', 'Tate', 'Upton', 'Vega', 'Wells', 'Xiong',
    'Young', 'Zale', 'Archer', 'Bryant', 'Chase', 'Dalton',
]
CITIES = ['Spokane', 'Cheney', 'Pullman', 'Yakima', 'Tacoma', 'Seattle']
STATES = ['WA', 'ID', 'OR']
GRADE_LEVELS = ['FR', 'SO', 'JR', 'SR']


class Command(BaseCommand):
    help = 'Seed demo students (via verify + profile forms) for onboarding-tab testing.'

    def add_arguments(self, parser):
        parser.add_argument('--prefix', type=str, default='demo',
                            help='Email/username prefix for generated users.')
        parser.add_argument('--highschool', type=str, default=None,
                            help='High school name to attach. Defaults to first Active HS.')

    @transaction.atomic
    def handle(self, *args, **opts):
        term = active_term()
        if term is None:
            self.stderr.write(self.style.ERROR('No active term — aborting.'))
            return

        hs_qs = HighSchool.objects.filter(status__iexact='Active').exclude(name__icontains='career')
        if opts['highschool']:
            hs_qs = hs_qs.filter(name=opts['highschool'])
        highschool = hs_qs.first()
        if highschool is None:
            self.stderr.write(self.style.ERROR('No active non-CTE HighSchool found — aborting.'))
            return

        prefix = opts['prefix']
        cohorts = [
            ('pending_verification', 'pending verification'),
            ('missing_ferpa',       'verified but missing FERPA'),
            ('ferpa_done',          'verified with FERPA complete'),
        ]
        created = {label: 0 for _, label in cohorts}

        for key, label in cohorts:
            for i in range(10):
                student = self._seed_one(prefix, key, i, highschool)
                if student:
                    self._apply_cohort_state(student, key)
                    created[label] += 1

        for _, label in cohorts:
            self.stdout.write(self.style.SUCCESS(f'Created {created[label]} students — {label}'))

    # ---------- helpers ----------

    def _seed_one(self, prefix, cohort_key, i, highschool):
        tag = f'{prefix}-{cohort_key}-{i:02d}'
        email = f'{tag}@example.com'

        if Student.objects.filter(user__username__iexact=email).exists():
            return Student.objects.get(user__username__iexact=email)

        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)

        # --- Step 1: StudentVerifyEmailForm.save() ---
        verify_form = StudentVerifyEmailForm()
        verify_form.cleaned_data = {
            'first_name': first,
            'last_name': last,
            'middle_name': '',
            'email': email,
            'confirm_email': email,
        }
        student = verify_form.save()

        # --- Step 2: StudentProfileForm.save() with full cleaned_data ---
        profile_form = StudentProfileForm(student=student)
        profile_form.cleaned_data = self._build_profile_cleaned_data(
            first, last, email, highschool, i
        )
        profile_form.save(student)

        return student

    def _build_profile_cleaned_data(self, first, last, email, highschool, seed):
        rnd = random.Random(seed)
        today = datetime.date.today()
        dob_year = today.year - rnd.randint(15, 18)
        dob = datetime.date(dob_year, rnd.randint(1, 12), rnd.randint(1, 28))
        grad_year = today.year + rnd.randint(1, 3)
        grad_date = datetime.date(grad_year, 6, 15)
        phone = f'509555{rnd.randint(1000, 9999):04d}'

        return {
            # Names
            'first_name': first,
            'last_name': last,
            'middle_name': '',
            'preferred_name': first,
            'other_last_names_used': '',

            # Email/password (password skipped; handled separately in save)
            'email': email,
            'password': '',
            'confirm_password': '',

            # Address — permanent
            'permanent_address_country': 'United States',
            'permanent_address': f'{100 + seed} Demo Street',
            'city': rnd.choice(CITIES),
            'county': 'Spokane',
            'state': rnd.choice(STATES),
            'zip_code': '99001',

            # Mailing (same as permanent)
            'same_as_permanent': True,
            'mailing_address': f'{100 + seed} Demo Street',
            'mailing_city': rnd.choice(CITIES),
            'mailing_county': 'Spokane',
            'mailing_state': rnd.choice(STATES),
            'mailing_zip_code': '99001',

            # Phones
            'preferred_phone': 'cell',
            'cell_phone': phone,
            'home_phone': phone,
            'cell_phone_opt_in': True,

            # Demographics
            'date_of_birth': dob,
            'legal_sex': rnd.choice(['m', 'f']),
            'gender': '',
            'country_of_birth': 'USA',
            'primary_citizenship': 'USA',
            'ssn': '',
            'verify_student_ssn': '',
            'hispanic': False,
            'ethnicity': [],

            # Parent/Guardian
            'parent_email': f'parent-{seed}-{email}',
            'parent_phone': phone,
            'parent_name': f'Parent of {first} {last}',

            # School
            'highschool': highschool,
            'cte': None,
            'current_grade_level': rnd.choice(GRADE_LEVELS),
            'graduation_date': grad_date,
            'signature': f'{first} {last}',
        }

    def _apply_cohort_state(self, student, cohort_key):
        # Seed default onboarding steps for the active term.
        onboarding_event.send(
            sender=__name__, event=oe.APPLICATION_STARTED, student=student,
        )

        if cohort_key == 'pending_verification':
            # Ensure account stays unverified and verify_email step is pending.
            if student.account_verified:
                student.account_verified = False
                student.verification_id = uuid.uuid4()
                student.save(update_fields=['account_verified', 'verification_id'])
            return

        # Verified cohorts.
        if not student.account_verified:
            student.account_verified = True
            student.verification_id = None
            student.save(update_fields=['account_verified', 'verification_id'])
        onboarding_event.send(
            sender=__name__, event=oe.EMAIL_VERIFIED, student=student,
        )

        if cohort_key == 'ferpa_done':
            onboarding_event.send(
                sender=__name__, event=oe.FERPA_COMPLETED, student=student,
            )
        # `missing_ferpa` cohort: verified, ferpa remains pending.
