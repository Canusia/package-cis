"""Email CE when a high school uploads a file (#56).

The HS-admin upload endpoint (package-highschool_admin) calls
notify_hs_upload() after saving. CE uploads from the high school record do
not, since the person who would be emailed is the one uploading.
"""
from django.conf import settings
from django.contrib.sites.models import Site
from django.template import Context, Template

from mailer import send_mail


def uploads_review_url():
    domain = Site.objects.get_current().domain
    if not domain.startswith('http'):
        domain = f'https://{domain}'
    return f'{domain}/ce/students/support_docs/#hs_uploads'


def notify_hs_upload(transcript):
    """Email the hs_uploads notify list; returns the addresses queued ([] if none)."""
    from cis.settings.hs_uploads import hs_uploads

    recipients = hs_uploads.notify_recipients()
    if not recipients:
        return []

    config = hs_uploads.get_config()
    uploader = transcript.uploaded_by
    context = Context({
        'highschool': transcript.highschool.name,
        'term': transcript.term.label if transcript.term_id else 'no term',
        'uploaded_by': f'{uploader.first_name} {uploader.last_name}'.strip()
                       or uploader.email,
        'description': transcript.description,
        'file_name': transcript.file_name,
        'link': uploads_review_url(),
    })
    subject = ' '.join(Template(config.get('notify_subject') or '')
                       .render(context).split())
    body = Template(config.get('notify_email') or '').render(context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)
    return recipients
