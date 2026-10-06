"""Term parent/sub-term helpers.

A Term may have a `parent` (related_name `sub_terms`) -- e.g. a "Fall Quarter"
term whose sections all live on its "Fall Semester" / "Fall Trimester" sub-terms.
These helpers let pickers show that hierarchy and let filters treat a parent
term as "this term and everything under it".

    from cis.services.term_hierarchy import term_tree_choices, filter_by_term

    choices = term_tree_choices(Term.objects.order_by('-code'))
    sections = filter_by_term(ClassSection.objects.all(), request.GET.get('term'))
"""
import uuid


def term_tree(terms=None):
    """[(term, depth)] with each term followed by its sub-terms, recursively.

    Siblings keep the order of `terms` (default: all terms, model ordering). A
    term whose parent is not in `terms` is treated as top-level, so a filtered
    list never loses a term. Safe against cycles in the data.
    """
    from cis.models.term import Term

    if terms is None:
        terms = Term.objects.all()
    terms = list(terms)

    ids = {term.pk for term in terms}
    children = {}
    roots = []
    for term in terms:
        if term.parent_id and term.parent_id in ids and term.parent_id != term.pk:
            children.setdefault(term.parent_id, []).append(term)
        else:
            roots.append(term)

    result = []
    seen = set()

    def walk(term, depth):
        if term.pk in seen:
            return
        seen.add(term.pk)
        result.append((term, depth))
        for child in children.get(term.pk, []):
            walk(child, depth + 1)

    for term in roots:
        walk(term, 0)
    # Terms only reachable through a cycle never hang off a root; keep them.
    for term in terms:
        if term.pk not in seen:
            walk(term, 0)
    return result


def term_tree_choices(terms=None, label=str, indent='   '):
    """[(id, label)] in term_tree order, sub-terms indented under their parent.

    `label` turns a term into its text (default str(term)); `indent` is
    repeated once per level (non-breaking spaces, so browsers keep it).
    """
    return [
        (str(term.pk), indent * depth + label(term))
        for term, depth in term_tree(terms)
    ]


def term_with_descendant_ids(term_id):
    """{term_id} plus the ids of all its sub-terms, recursively.

    One query for the (id, parent) pairs however deep the tree is; safe
    against cycles. Returns an empty set for an id that is not a UUID.
    """
    from cis.models.term import Term

    try:
        root = uuid.UUID(str(term_id))
    except (ValueError, TypeError, AttributeError):
        return set()

    children = {}
    for pk, parent_id in Term.objects.filter(
            parent__isnull=False).values_list('pk', 'parent_id'):
        children.setdefault(parent_id, []).append(pk)

    found = {root}
    pending = [root]
    while pending:
        for child in children.get(pending.pop(), []):
            if child not in found:
                found.add(child)
                pending.append(child)
    return found


def filter_by_term(queryset, term_id, field='term'):
    """Filter `queryset` to `term_id` and its sub-terms.

    `field` is the lookup path to the Term (e.g. 'class_section__term' for
    registrations). An id that is not a UUID matches nothing.
    """
    return queryset.filter(**{f'{field}__in': term_with_descendant_ids(term_id)})
