"""Preview of a page-header text ("blurb") setting, for the settings "See Preview" link.

The HS admin pages render their blurb raw at the top of the page, so the most
faithful preview is the stored text on its own. Rendering the whole portal page
with an empty context (the old approach) dropped a complete HTML document into
the settings modal and broke for any page it did not know (package-cis#111).
"""
from django.shortcuts import render

TEMPLATE = 'cis/includes/blurb_preview.html'


def render_blurb_preview(request, page_label, blurb):
    """Render ``blurb`` (trusted, CE-authored HTML) as it heads ``page_label``."""
    return render(request, TEMPLATE, {
        'page_label': page_label,
        'blurb': blurb if isinstance(blurb, str) and blurb.strip() else '',
    })
