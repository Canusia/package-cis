"""High school <-> campus link signals.

* A new HighSchool is linked as Active to the campus it was created under.
* HighSchool.status is derived from the school's campus links: Active if any
  link is Active, else Inactive; unchanged when the school has no links. It is
  written with ``.update()`` so no HighSchool signals (or history) fire.
"""
import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from cis.campus_context import current_campus_or_none, deployment_campus, is_multi_campus
from cis.models.highschool import HighSchool, HighSchoolCampus

logger = logging.getLogger(__name__)


def derived_status(highschool_pk):
    """'Active'/'Inactive' from the school's links, or None when it has none."""
    statuses = list(HighSchoolCampus.objects.filter(
        highschool_id=highschool_pk).values_list('status', flat=True))
    if not statuses:
        return None
    return 'Active' if 'Active' in statuses else 'Inactive'


@receiver(post_save, sender=HighSchool)
def link_new_highschool(sender, instance, created=False, raw=False, **kwargs):
    if raw or not created:
        return
    campus = current_campus_or_none() if is_multi_campus() else deployment_campus()
    if campus is None:
        logger.warning(
            'New high school %s (%s) has no campus to link to; left unlinked.',
            instance.pk, instance)
        return
    HighSchoolCampus.objects.get_or_create(
        highschool=instance, campus=campus, defaults={'status': 'Active'})


@receiver(pre_save, sender=HighSchool)
def derive_status_before_save(sender, instance, raw=False, **kwargs):
    if raw or instance._state.adding:
        return
    status = derived_status(instance.pk)
    if status is not None:
        instance.status = status


def _recompute(highschool_id):
    status = derived_status(highschool_id)
    if status is not None:
        HighSchool.objects.filter(pk=highschool_id).update(status=status)


@receiver(post_save, sender=HighSchoolCampus)
def recompute_on_link_save(sender, instance, raw=False, **kwargs):
    if not raw:
        _recompute(instance.highschool_id)


@receiver(post_delete, sender=HighSchoolCampus)
def recompute_on_link_delete(sender, instance, **kwargs):
    _recompute(instance.highschool_id)
