"""Template filters for term pickers that follow the parent/sub-term tree.

    {% load term_tree %}
    {% for c in terms|term_tree %}
        <option value="{{ c.id }}">{{ c|term_indent }}{{ c.label }}</option>
    {% endfor %}
"""
from django import template
from django.utils.safestring import mark_safe

from cis.services.term_hierarchy import term_tree as _term_tree

register = template.Library()


@register.filter(name='term_tree')
def term_tree(terms):
    """`terms` in tree order, each tagged with `.tree_depth`."""
    if not terms:
        return []
    ordered = []
    for term, depth in _term_tree(terms):
        term.tree_depth = depth
        ordered.append(term)
    return ordered


@register.filter
def term_indent(term):
    """Three non-breaking spaces per level of `term.tree_depth`."""
    return mark_safe('&nbsp;' * 3 * getattr(term, 'tree_depth', 0))
