from cis.shortcodes import render_shortcodes

DEFAULT_BODIES = {
    "student": (
        '[breadcrumb label="Student"]\n'
        "[messages]\n"
        '<div class="row">\n'
        '  <div class="col-md-6 col-sm-12 mt-2"><div class="card"><div class="card-body">\n'
        '    <h5 class="card-title mb-3">Please log in if you have already created an account</h5>\n'
        "    [login_form]\n"
        "  </div></div></div>\n"
        '  <div class="col-md-6 col-sm-12 mt-2"><div class="card"><div class="card-body">\n'
        "    [start_app label=\"Start New Application\"]\n"
        "  </div></div></div>\n"
        "</div>"
    ),
    "instructor": (
        '[breadcrumb label="Instructor"]\n'
        "[messages]\n"
        '<div class="card border-top-0"><div class="card-body">\n'
        '  <h3 class="mb-4">Current Instructors, please login below using your school email address</h3>\n'
        '  <div class="row">\n'
        '    <div class="col-md-6 col-sm-12"><h5 class="card-title mb-3">Please login below</h5>[login_form]</div>\n'
        '    <div class="col-md-6 col-sm-12 mt-2">[start_app label="Start New Application"]</div>\n'
        "  </div>\n"
        "</div></div>"
    ),
    "faculty": (
        '[breadcrumb label="Faculty"]\n'
        "[messages]\n"
        '<div class="row"><div class="col-md-6 col-sm-12"><div class="card"><div class="card-body">\n'
        "  Click below to login with your college login information\n"
        '  [sso_login label="Login Now"]\n'
        "</div></div></div></div>"
    ),
    "staff": (
        '[breadcrumb label="College Administrator"]\n'
        "[messages]\n"
        '<div class="row"><div class="col-md-6 col-sm-12"><div class="card"><div class="card-body">\n'
        "  Click below to login with your college login information\n"
        '  [sso_login label="Login Now"]\n'
        "</div></div></div></div>"
    ),
    "counselor": (
        "[breadcrumb]\n"
        "[messages]\n"
        '<div class="row">\n'
        '  <div class="col-md-6 col-sm-12"><div class="card"><div class="card-body">\n'
        '    <h5 class="card-title mb-3">Please login below using your school email address</h5>\n'
        "    [login_form forgot_label=\"Reset Password\"]\n"
        "  </div></div></div>\n"
        '  <div class="col-md-6">\n'
        '    <p class="alert alert-info">If you do not have access to the portal, please submit a request</p>\n'
        "    [start_app]\n"
        "  </div>\n"
        "</div>"
    ),
}


def render_landing_body(request, role, context):
    from cis.settings.portal_content import portal_content

    stored = portal_content.from_db().get(f"{role}_body")
    body = stored if stored else DEFAULT_BODIES.get(role, "")
    ctx = dict(context)
    ctx["role"] = role
    return render_shortcodes(body, request, ctx)
