from django.conf import settings


def export_vars(request):
    """MYCE_SETTINGS with the current campus's names (package-cis #61); a copy,
    so settings.MY_CE itself is never changed."""
    from cis.branding import current_brand
    return {'MYCE_SETTINGS': {**settings.MY_CE, **current_brand().names()}}
