"""Email the student when a StudentSupportingDocument's status changes.

Gated on the `email_enabled` flag in the merged `support_docs` setting. The
status-change email body/subject also come from that setting.

Note: only per-instance ``.save()`` fires these signals — the mark-status bulk
action saves each document individually for exactly this reason. A bare
``QuerySet.update(status=...)`` would bypass this.
"""
import logging

from django.conf import settings
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.template import Context, Template
from django.template.loader import get_template

from mailer import send_html_mail

from ..models.student import StudentSupportingDocument

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=StudentSupportingDocument)
def capture_support_doc_status_change(sender, instance, **kwargs):
    """Record whether `status` changed vs. the persisted row (for post_save)."""
    if not instance.pk:
        instance._status_changed = False
        return
    old_status = (sender.objects
                  .filter(pk=instance.pk)
                  .values_list('status', flat=True)
                  .first())
    instance._status_changed = (old_status is not None and old_status != instance.status)


@receiver(post_save, sender=StudentSupportingDocument)
def email_on_support_doc_status_change(sender, instance, created, **kwargs):
    if created or not getattr(instance, '_status_changed', False):
        return
    if not instance.status:
        return

    from cis.settings.support_docs import support_docs
    cfg = support_docs.get_config()
    if cfg.get('email_enabled', 'No') != 'Yes':
        return

    student = instance.student
    user = getattr(student, 'user', None)
    to_email = getattr(user, 'email', None)
    if not to_email:
        return

    text_body = Template(cfg.get('status_change_email', '')).render(Context({
        'student_first_name': user.first_name,
        'student_last_name': user.last_name,
        'document_type': instance.document_type,
        'status': instance.status,
    }))
    html_body = get_template('cis/email.html').render({'message': text_body})
    subject = cfg.get('status_change_email_subject') or 'Document status updated'

    to = [to_email]
    if getattr(settings, 'DEBUG', True):
        to = ['kadaji@gmail.com']

    try:
        send_html_mail(
            subject,
            text_body,
            html_body,
            settings.DEFAULT_FROM_EMAIL,
            to,
        )
    except Exception as e:
        logger.error(f'Failed to send support-doc status-change email: {e}')
