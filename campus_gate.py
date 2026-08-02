"""CE-staff campus gate.

CE ('ce') staff are scoped to the campuses listed in
``CustomUser.campus['process_campus']``. This module centralises reading that
list, resolving the campuses to show in a dropdown, the object-level
permission check, a queryset-scoping helper, and the ``campus_gate`` view
decorator. Records with no campus (``campus is None``) are visible/editable to
every ce user. Superusers bypass all scoping.
"""
import uuid
from functools import wraps

from django.conf import settings
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from cis.utils import user_has_cis_role


def _prefixed_campuses():
    from cis.models.course import Campus
    return Campus.objects.filter(code__startswith=settings.CAMPUS_CODE_PREFIX)


def get_process_campus_ids(user):
    """Campus-id strings this user may process.

    Superuser -> all prefixed campus ids. ce user -> their
    ``process_campus`` list (strings). Anyone else / no data -> [].
    """
    if getattr(user, 'is_superuser', False):
        return [str(pk) for pk in _prefixed_campuses().values_list('id', flat=True)]

    if not user_has_cis_role(user):
        return []

    campus = getattr(user, 'campus', None)
    if campus:
        return [str(c) for c in (campus.get('process_campus') or [])]
    return []


def get_accessible_campuses(user):
    """Campus queryset for the filter dropdown (prefixed campuses only)."""
    campuses = _prefixed_campuses()
    if getattr(user, 'is_superuser', False):
        return campuses
    return campuses.filter(id__in=get_process_campus_ids(user))


def can_process_campus(user, campus):
    """Object-level check: may ``user`` act on a record in ``campus``?"""
    if getattr(user, 'is_superuser', False):
        return True
    if not user_has_cis_role(user):
        return False
    if campus is None:
        return True
    return str(campus.id) in get_process_campus_ids(user)


def scope_queryset_by_campus(records, user, campus_path='campus',
                             selected_campus=None):
    """Narrow ``records`` to the user's processable campuses OR null campus.

    Only ce staff are campus-scoped. Superusers and non-ce roles are returned
    unchanged — non-ce roles carry their own upstream scoping (e.g. instructor
    by taught sections), which this must not override. ``selected_campus`` (a
    campus-id string from a page's dropdown) narrows to that one campus, but
    only if the user may process it — it can never widen the scope.
    """
    if getattr(user, 'is_superuser', False):
        return records
    if not user_has_cis_role(user):
        return records
    ids = get_process_campus_ids(user)
    if selected_campus and selected_campus in ids:
        campus_ids = [selected_campus]
    else:
        campus_ids = ids
    return records.filter(
        Q(**{f'{campus_path}__id__in': campus_ids})
        | Q(**{f'{campus_path}__isnull': True})
    )


def processable_ids(model, ids, user, campus_path='campus'):
    """Return the subset of `ids` the user may act on (campus-scoped).

    Superusers and non-ce roles get their (existing, valid) ids back unchanged
    because scope_queryset_by_campus is a no-op for them; ce staff get only ids
    whose campus (via `campus_path`) is processable or null. Non-UUID or
    non-existent ids are dropped. Input order is preserved.
    """
    if not ids:
        return ids
    valid = []
    for i in ids:
        try:
            uuid.UUID(str(i))
            valid.append(i)
        except (ValueError, AttributeError, TypeError):
            pass
    if not valid:
        return []
    scoped = scope_queryset_by_campus(
        model.objects.filter(id__in=valid), user, campus_path)
    keep = {str(pk) for pk in scoped.values_list('id', flat=True)}
    return [i for i in valid if str(i) in keep]


# --- Student campus gate -----------------------------------------------------
# A Student has no campus FK. A student is associated with a campus by having
# *applied for a class* there: a StudentRegistration whose
# class_section -> course -> campus is one the ce user processes. Unverified
# students (account_verified=False) are not yet tied to any campus, so they are
# universally visible/editable/actionable — the student analogue of a
# null-campus record.
_STUDENT_CAMPUS_PATH = 'studentregistration__class_section__course__campus'


def scope_students_by_campus(students, user, selected_campus=None):
    """Narrow a Student queryset for a ce user.

    ce user sees students who applied at one of their processable campuses OR
    whose account is not verified. ``selected_campus`` (a campus-id string from
    the dropdown) narrows the applied-at set to that one campus, but only if the
    user may process it — it can never widen the scope. Superusers and non-ce
    roles are returned unchanged (their upstream role scoping governs).
    """
    if getattr(user, 'is_superuser', False):
        return students
    if not user_has_cis_role(user):
        return students
    ids = get_process_campus_ids(user)
    if selected_campus and selected_campus in ids:
        campus_ids = [selected_campus]
    else:
        campus_ids = ids
    return students.filter(
        Q(**{f'{_STUDENT_CAMPUS_PATH}__id__in': campus_ids})
        | Q(account_verified=False)
    ).distinct()


def scope_records_by_student_campus(records, user, student_path='student',
                                    include_null_student=False,
                                    selected_campus=None):
    """Narrow a *student-backed* model's records to a ce user's campuses.

    For models that have no campus FK of their own but reference a Student
    (e.g. notes, recommendations, supporting docs, tuition assistance,
    transactions): keep only records whose student is visible under
    ``scope_students_by_campus`` (applied at a processable campus, or
    unverified). Superusers and non-ce roles are returned unchanged. When
    ``include_null_student`` is True, records with no student are always kept —
    the student analogue of the null-campus allowance. ``selected_campus`` (a
    campus-id string from the page's dropdown) narrows within the user's
    accessible campuses; it can never widen the scope.
    """
    if getattr(user, 'is_superuser', False):
        return records
    if not user_has_cis_role(user):
        return records
    from cis.models.student import Student
    scoped_students = scope_students_by_campus(
        Student.objects.all(), user, selected_campus=selected_campus)
    q = Q(**{f'{student_path}__in': scoped_students})
    if include_null_student:
        q |= Q(**{f'{student_path}__isnull': True})
    return records.filter(q)


def can_access_student(user, student):
    """Object-level check: may ``user`` view/edit this student's record?

    True for superusers; False for non-ce; True for any unverified student;
    otherwise True only if the student applied at a campus the user processes.
    """
    if getattr(user, 'is_superuser', False):
        return True
    if not user_has_cis_role(user):
        return False
    if not student.account_verified:
        return True
    ids = get_process_campus_ids(user)
    return student.studentregistration_set.filter(
        class_section__course__campus__id__in=ids
    ).exists()


def processable_student_ids(ids, user):
    """Subset of student ids the user may act on in a bulk action.

    Unverified students are always kept; verified students only if the user
    processes a campus they applied at. Non-UUID ids are dropped; order kept.
    """
    if not ids:
        return ids
    from cis.models.student import Student
    valid = []
    for i in ids:
        try:
            uuid.UUID(str(i))
            valid.append(i)
        except (ValueError, AttributeError, TypeError):
            pass
    if not valid:
        return []
    scoped = scope_students_by_campus(Student.objects.filter(id__in=valid), user)
    keep = {str(pk) for pk in scoped.values_list('id', flat=True)}
    return [i for i in valid if str(i) in keep]


def scope_report_by_campus(records, user, selected_campus_ids, campus_path,
                           distinct=False):
    """Campus-scope a report queryset to the selected campuses.

    ``selected_campus_ids`` is the raw value of a report's required multi-select
    campus field (a list of id strings, or a single id). ``campus_path`` is the
    ORM path from the record to ``Campus`` (e.g. ``class_section__course__campus``,
    ``course__campus``, ``student__studentregistration__class_section__course__campus``).

    For a ce requester the selection is constrained to their processable
    campuses (defence-in-depth against a tampered/stale scheduled re-run); a ce
    requester whose selection resolves to nothing gets ``records.none()``.
    Superusers and non-ce roles use the selection as-is. Pass ``distinct=True``
    when ``campus_path`` traverses a to-many relation (student/registration
    joins) to avoid duplicate rows.
    """
    if not isinstance(selected_campus_ids, (list, tuple)):
        selected_campus_ids = [selected_campus_ids]
    ids = [str(c) for c in selected_campus_ids if c]

    if user is not None and user_has_cis_role(user) \
            and not getattr(user, 'is_superuser', False):
        allowed = set(get_process_campus_ids(user))
        ids = [c for c in ids if c in allowed]
        if not ids:
            return records.none()

    if not ids:
        return records
    scoped = records.filter(**{f'{campus_path}__id__in': ids})
    return scoped.distinct() if distinct else scoped


def scope_by_course_cert_campus(records, user, cert_path, selected_campus=None):
    """Scope teacher-like records by the campuses of the courses they are
    certified to teach; a record with NO course certificate is universal
    (visible in every campus) — the teacher analogue of an unverified student.

    ``cert_path`` is the ORM path from the record to a TeacherCourseCertificate
    (``'teacherhighschool__teachercoursecertificate'`` from Teacher,
    ``'teachercoursecertificate'`` from TeacherHighSchool). ``selected_campus``
    (from the page's dropdown) narrows to one campus, but never past the ce
    user's processable set; superusers may narrow via the dropdown too but are
    otherwise unscoped. Non-ce roles are returned unchanged.
    """
    is_super = getattr(user, 'is_superuser', False)
    if not is_super and not user_has_cis_role(user):
        return records
    if is_super:
        campus_ids = [selected_campus] if selected_campus else None
    else:
        ids = get_process_campus_ids(user)
        campus_ids = ([selected_campus]
                      if selected_campus and selected_campus in ids else ids)
    if campus_ids is None:
        return records
    no_cert_ids = records.model.objects.exclude(
        **{f'{cert_path}__isnull': False}).values('id')
    return records.filter(
        Q(**{f'{cert_path}__course__campus__id__in': campus_ids})
        | Q(id__in=no_cert_ids)
    ).distinct()


def campus_gate(model, campus_of=None, mode='page', pk_kwarg='record_id'):
    """Block object-level access when the user can't process the record's campus.

    ``model``      — the model to load by pk.
    ``campus_of``  — callable(record) -> Campus|None (default: record.campus).
    ``mode``       — 'page' (render 403 html) or 'json' (403 JsonResponse).
    ``pk_kwarg``   — name of the pk kwarg passed to the wrapped view.
    """
    resolve_campus = campus_of or (lambda obj: obj.campus)

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            pk = kwargs.get(pk_kwarg)
            if pk is None and args:
                pk = args[0]
            record = get_object_or_404(model, pk=pk)
            if not can_process_campus(request.user, resolve_campus(record)):
                message = 'You are not authorized to access this campus.'
                if mode == 'json':
                    return JsonResponse(
                        {'status': 'error', 'message': message}, status=403)
                return render(
                    request, 'cis/not_authorized.html',
                    {'message': message}, status=403)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
