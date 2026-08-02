"""Dev-only helper for the Playwright e2e suite.

Creates (or reuses) a Django session for the given user and prints the
sessionid cookie value. The Playwright `global-setup.ts` script consumes
this and injects the cookie via `BrowserContext.addCookies(...)`, which
sidesteps the form-login flow entirely (the project's index pages all
require Google reCAPTCHA, which we can't satisfy programmatically).

Usage:
    docker exec -w /app/webapp django_web_ewu \\
        python manage.py e2e_login --email e2e-playwright@example.com

Refuses to run unless `DEPLOY_TYPE` is `local`, `dev`, or `preview` so it
can never accidentally land in production.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand, CommandError


SAFE_DEPLOY_TYPES = {'local', 'dev', 'preview'}


class Command(BaseCommand):
    help = 'Issue a Django session for an e2e test user and print the sessionid.'

    def add_arguments(self, parser):
        parser.add_argument('--email', required=True)
        parser.add_argument(
            '--ttl-days', type=int, default=7,
            help='Session lifetime in days (default: 7).',
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
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise CommandError(f'No user with email={email!r}')

        if not user.is_active:
            raise CommandError(f'User {email!r} is not active')

        # Pick the auth backend so AuthenticationMiddleware will accept the
        # session. EmailAuthBackend is the project's primary backend (see
        # webapp/myce/settings.py AUTHENTICATION_BACKENDS).
        backend = 'cis.email_backend.EmailAuthBackend'

        session = SessionStore()
        session['_auth_user_id'] = str(user.pk)
        session['_auth_user_backend'] = backend
        session['_auth_user_hash'] = user.get_session_auth_hash()
        session.set_expiry(opts['ttl_days'] * 24 * 60 * 60)
        session.save()

        # Print only the cookie value to stdout so the caller can shell-capture it.
        # Diagnostics go to stderr.
        self.stderr.write(f'Issued session for {email} (expires in {opts["ttl_days"]} days)')
        self.stdout.write(session.session_key)
