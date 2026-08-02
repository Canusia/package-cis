"""Dev-only helper for the Playwright student-onboarding e2e suite.

Looks up or deletes a Student by email, returning the UUIDs the onboarding
URLs require. The Playwright spec uses this to bridge the email-verification
gap without parsing an SMTP inbox.

Usage:
    docker exec -w /app/webapp django_web_ewu \\
        python manage.py e2e_student --email foo@example.com --action get
    docker exec -w /app/webapp django_web_ewu \\
        python manage.py e2e_student --email foo@example.com --action delete

`get` prints a single line of JSON with `verification_id` and `student_id`
(either may be null depending on flow state). `delete` removes the Student
*and* the associated CustomUser so the same email can be reused next run.

Refuses to run unless `DEPLOY_TYPE` is `local`, `dev`, or `preview` so it
can never accidentally land in production.
"""
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from cis.models.student import Student


SAFE_DEPLOY_TYPES = {'local', 'dev', 'preview'}


class Command(BaseCommand):
    help = 'Look up or delete a Student by email for the e2e suite.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument(
            '--action', choices=('get', 'delete'), default='get',
            help='`get` prints {verification_id, student_id}; `delete` removes the row.',
        )

    def handle(self, *args, **opts):
        deploy_type = getattr(settings, 'DEPLOY_TYPE', None)
        if deploy_type not in SAFE_DEPLOY_TYPES:
            raise CommandError(
                f'Refusing to run with DEPLOY_TYPE={deploy_type!r}; '
                f'only {sorted(SAFE_DEPLOY_TYPES)} are allowed.'
            )

        email = opts['email']
        User = get_user_model()

        if opts['action'] == 'delete':
            user_qs = User.objects.filter(email=email)
            count = user_qs.count()
            # Student.user is on_delete=PROTECT, so we have to delete the
            # Student rows explicitly before the User itself.
            Student.objects.filter(user__in=user_qs).delete()
            user_qs.delete()
            self.stderr.write(f'Deleted {count} user(s) for email={email!r}')
            self.stdout.write(json.dumps({'deleted': count}))
            return

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            self.stdout.write(json.dumps({'verification_id': None, 'student_id': None}))
            return

        student = Student.objects.filter(user=user).first()
        payload = {
            'verification_id': str(student.verification_id) if student and student.verification_id else None,
            'student_id': str(student.id) if student else None,
            'account_verified': bool(student.account_verified) if student else None,
        }
        self.stdout.write(json.dumps(payload))
