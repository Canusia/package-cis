"""High school <-> campus link signals and the helpers they share.

* A new HighSchool is linked to the campus it was created under, with the school's own status.
* HighSchool.status is derived from the school's campus links: Active if any
  link is Active, else Inactive; unchanged when the school has no links. It is
  written with ``.update()`` so no HighSchool signals (or history) fire.

The helpers below are the single place that rule lives. Code that bypasses
model signals (``bulk_create``, ``bulk_update``, ``.update()``) or writes a
school-level status (CSV import, the status form, a merge) goes through them:
``link_campus``, ``link_status``, ``link_new_highschools``,
``set_link_status``, ``set_link_statuses``, ``recompute_statuses`` and
``merge_campus_links``.
"""
import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from simple_history.utils import bulk_create_with_history, bulk_update_with_history

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


def link_campus():
    """The campus a school-level write lands on.

    Single-campus: the deployment campus. Multi-campus: the current campus,
    or None outside any campus context.
    """
    return current_campus_or_none() if is_multi_campus() else deployment_campus()


def link_status(value):
    """A school status as a link status: 'Active' (any case) or 'Inactive'."""
    return 'Active' if (value or '').strip().lower() == 'active' else 'Inactive'


def recompute_statuses(highschool_ids):
    """Write the derived status of each school with links (one query per status)."""
    ids = set(highschool_ids)
    if not ids:
        return
    linked, active = set(), set()
    for hs_id, status in HighSchoolCampus.objects.filter(
            highschool_id__in=ids).values_list('highschool_id', 'status'):
        linked.add(hs_id)
        if status == 'Active':
            active.add(hs_id)
    if active:
        HighSchool.objects.filter(pk__in=active).update(status='Active')
    if linked - active:
        HighSchool.objects.filter(pk__in=linked - active).update(status='Inactive')


def _warn_no_campus(highschools):
    for hs in highschools:
        logger.warning(
            'New high school %s (%s) has no campus to link to; left unlinked.',
            hs.pk, hs)


def link_new_highschools(highschools, campus=None):
    """Link schools that ``bulk_create`` saved (no post_save fired).

    Same campus rule and status mapping as ``link_new_highschool``. Schools
    already linked to the campus are skipped. Returns the links created.
    """
    highschools = list(highschools)
    if not highschools:
        return []
    campus = campus or link_campus()
    if campus is None:
        _warn_no_campus(highschools)
        return []
    have = set(HighSchoolCampus.objects.filter(
        campus=campus, highschool__in=highschools).values_list('highschool_id', flat=True))
    links = [HighSchoolCampus(highschool=hs, campus=campus, status=link_status(hs.status))
             for hs in highschools if hs.pk not in have]
    if links:
        bulk_create_with_history(links, HighSchoolCampus)
    recompute_statuses(hs.pk for hs in highschools)
    return links


def set_link_status(highschool, status, campus):
    """Set the school's link status on ``campus``, creating the link if missing.

    The school's derived status follows (via the link's post_save). Returns
    True when the link was created or its status changed.
    """
    link, created = HighSchoolCampus.objects.get_or_create(
        highschool=highschool, campus=campus, defaults={'status': status})
    if created:
        return True
    if link.status == status:
        return False
    link.status = status
    link.save()
    return True


def set_link_statuses(statuses, campus):
    """Bulk ``set_link_status``: ``statuses`` maps school pk -> link status.

    For importers: creates missing links, updates changed ones and re-derives
    every touched school's status in a fixed number of queries.
    """
    if not statuses:
        return
    existing = {link.highschool_id: link for link in HighSchoolCampus.objects.filter(
        campus=campus, highschool_id__in=list(statuses))}
    create, update = [], []
    for hs_id, status in statuses.items():
        link = existing.get(hs_id)
        if link is None:
            create.append(HighSchoolCampus(highschool_id=hs_id, campus=campus, status=status))
        elif link.status != status:
            link.status = status
            update.append(link)
    if create:
        bulk_create_with_history(create, HighSchoolCampus)
    if update:
        bulk_update_with_history(update, HighSchoolCampus, ['status'])
    recompute_statuses(statuses)


def merge_campus_links(source, target):
    """Fold ``source``'s campus links into ``target`` (a school merge).

    A link on a campus ``target`` is not linked to moves across with its
    building code and status; where both are linked, ``target``'s link is
    kept and ``source``'s dropped. ``target``'s status is then re-derived.
    """
    target_campuses = set(HighSchoolCampus.objects.filter(
        highschool=target).values_list('campus_id', flat=True))
    for link in HighSchoolCampus.objects.filter(highschool=source):
        if link.campus_id in target_campuses:
            link.delete()
        else:
            link.highschool = target
            link.save()
    recompute_statuses([target.pk])


@receiver(post_save, sender=HighSchool)
def link_new_highschool(sender, instance, created=False, raw=False, **kwargs):
    if raw or not created:
        return
    campus = link_campus()
    if campus is None:
        _warn_no_campus([instance])
        return
    # The link carries the school's own status, so the derived status equals
    # what was written (same mapping as the backfill).
    HighSchoolCampus.objects.get_or_create(
        highschool=instance, campus=campus,
        defaults={'status': link_status(instance.status)})


@receiver(pre_save, sender=HighSchool)
def derive_status_before_save(sender, instance, raw=False, **kwargs):
    if raw or instance._state.adding:
        return
    status = derived_status(instance.pk)
    if status is not None:
        instance.status = status


def _recompute(highschool_id):
    recompute_statuses([highschool_id])


@receiver(post_save, sender=HighSchoolCampus)
def recompute_on_link_save(sender, instance, raw=False, **kwargs):
    if not raw:
        _recompute(instance.highschool_id)


@receiver(post_delete, sender=HighSchoolCampus)
def recompute_on_link_delete(sender, instance, **kwargs):
    _recompute(instance.highschool_id)
