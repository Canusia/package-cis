from django.conf import settings

from django.utils.safestring import mark_safe
from django.contrib.auth.models import Group
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.contrib.sites.models import Site

from django.template import Context, Template
from django.template.loader import get_template, render_to_string

from mailer import send_mail, send_html_mail

from cis.models.highschool_administrator import (
    HSAdministratorPosition, HSAdministratorAccessRequest
)

@receiver(post_save, sender=HSAdministratorAccessRequest)
def hs_access_updated(sender, instance, created, **kwargs):
    try:
        if created:
            instance.notify_on_submit()
    except Exception as e:
        print(f"Error in hs_access_updated (HSAdministratorAccessRequest): {e}")

@receiver(post_save, sender=HSAdministratorPosition)
def hs_position_updated(sender, instance, created, **kwargs):
    hsadmin = instance.hsadmin
    active_hs = hsadmin.get_highschools()

    # get_or_create, not get: init_groups makes this group, but a deployment
    # that has not run it yet would raise Group.DoesNotExist out of a
    # post_save receiver, after the position row was written (#71).
    group, _ = Group.objects.get_or_create(name='highschool_admin')
    if not active_hs:
        hsadmin.user.groups.remove(group)
    else:
        hsadmin.user.groups.add(group)

    if instance.status.lower() != 'active':
        meta = {
            'manage_student_recommendation': 'No'
        }

        HSAdministratorPosition.objects.filter(
            id=instance.id
        ).update(
            meta=meta
        )