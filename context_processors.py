def export_vars(request):
    """MYCE_SETTINGS with the current campus's names (package-cis #61); a copy,
    so settings.MY_CE itself is never changed."""
    from cis.branding import branded_my_ce
    return {'MYCE_SETTINGS': branded_my_ce()}
