"""Which supporting documents a student's current courses require, and which
of those are still missing.

Informational only, like CourseDocumentRequirement itself: nothing here blocks
a registration. The answer is built from three things CE already configures:

* the course's Document Requirement(s) tab -- active, required rows that apply
  to the student's grade;
* the support_docs setting's "Registration Statuses Requiring Documents",
  which picks the registrations that count; and
* CourseDocumentRequirement.satisfied_for(), the single owner of the
  recurrence window and the satisfying-status rule. One upload covers every
  course needing the same document in the window, so rows are per
  (term, document), not per course.

Only the active term and the open registration terms are checked -- an old
term's enrolled courses would otherwise ask for documents forever.
"""
from dataclasses import dataclass, field

#: CourseDocumentRequirement.required stores YES_NO_SELECT_OPTIONS codes.
NOT_REQUIRED = '2'


@dataclass
class RequiredDocument:
    term: object
    label: str
    recurrence: str
    satisfied: bool
    linked: bool
    courses: list = field(default_factory=list)
    descriptions: list = field(default_factory=list)


def is_enabled():
    """The support_docs setting's "Show Missing Documents on Student Detail"."""
    from cis.settings.support_docs import support_docs
    return support_docs.get_config().get('show_missing_documents', 'No') == 'Yes'


def current_terms():
    """The active term plus the open registration terms."""
    from cis.utils import active_term, registration_terms

    terms = {}
    active = active_term()
    if active is not None:
        terms[active.pk] = active
    for term in registration_terms() or []:
        terms[term.pk] = term
    return list(terms.values())


def requirements_for(student, terms=None):
    """[RequiredDocument, ...] for `student`, missing ones first, then by term
    and label. Empty when the student's current courses require nothing."""
    from cis.models.course import CourseDocumentRequirement
    from cis.models.section import StudentRegistration
    from cis.settings.support_docs import support_docs

    terms = current_terms() if terms is None else list(terms)
    if not terms:
        return []

    registrations = list(StudentRegistration.objects.filter(
        student=student,
        class_section__term__in=terms,
        status__in=support_docs.get_document_check_registration_statuses(),
    ).select_related('class_section__course', 'class_section__term'))
    if not registrations:
        return []

    by_course = {}
    for requirement in CourseDocumentRequirement.objects.filter(
            course_id__in={r.class_section.course_id for r in registrations},
            status='Active',
    ).select_related('document_type'):
        if str(requirement.required) == NOT_REQUIRED:
            continue
        if not requirement.applies_to_grade(student.grade_level):
            continue
        by_course.setdefault(requirement.course_id, []).append(requirement)

    rows = {}
    for registration in registrations:
        section = registration.class_section
        for requirement in by_course.get(section.course_id, []):
            # Unlinked requirements cannot be matched to uploads; keep each one
            # its own row so it is visible rather than merged away.
            doc_key = requirement.document_type_id or f'unlinked:{requirement.pk}'
            key = (section.term_id, doc_key)
            row = rows.get(key)
            if row is None:
                row = rows[key] = RequiredDocument(
                    term=section.term,
                    label=requirement.document_label,
                    recurrence=requirement.get_recurrence_display(),
                    satisfied=requirement.satisfied_for(student, section.term),
                    linked=bool(requirement.document_type_id),
                )
            course = f'{section.course.name} {section.course.title}'.strip()
            if course not in row.courses:
                row.courses.append(course)
            if requirement.description and requirement.description not in row.descriptions:
                row.descriptions.append(requirement.description)

    return sorted(rows.values(), key=lambda r: (
        r.satisfied, getattr(r.term, 'code', ''), r.label.lower()))


def tab_context(student):
    """Context for the CE Supporting Documents tab: {} when the setting is off
    or nothing is required, so the tab renders exactly as before."""
    if not is_enabled():
        return {}
    required = requirements_for(student)
    if not required:
        return {}
    return {
        'required_documents': required,
        'missing_documents': [r for r in required if not r.satisfied],
    }
