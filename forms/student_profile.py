"""Student profile form modes. The FIELDS live in the tenant app.

cis owns the three modes a student profile is presented in — the full profile,
the post-SIS editable subset, and the CE-admin variant — because each is a
policy about who may change what, not a statement about which fields a tenant
collects. The field declarations, per-field validation and save behavior live in
`{TENANT_SERVICES_APP}.services.student_profile_form`.

The three public names are resolved lazily by module __getattr__, mirroring
cis.forms.student. Lazy matters here in a narrower sense than it might read:
*importing* cis.forms.student_profile never itself resolves the tenant app —
test_importing_the_module_does_not_resolve_the_tenant_app guards exactly that,
which is what keeps cis import-order-safe. But in practice the tenant module
IS already resolved at process boot: cis.apps.CisConfig.ready() calls
autodiscover_modules('page_messages'), and student/page_messages.py and
highschool_admin/.../page_messages.py both transitively import views that
import StudentProfileForm / StudentEditableForm at module level (see
student/views/dashboard.py and cis/views/faculty.py's chain through
student_import_schema.py). So by the time django.setup() returns, both derived
classes are already built and cached — verified directly against sys.modules
and _class_cache.

This is safe because ready() runs after BOTH apps_ready and models_ready are
True — Django's Apps.populate sets apps_ready at the end of Phase 1 and
models_ready after Phase 2, and runs ready() in Phase 3. So the tenant
module's `cis.models.*` imports, apps.get_models() and get_user_model() all
resolve fine at its own module level (measured inside CisConfig.ready():
apps_ready=True, models_ready=True). What is still False during ready() is
apps.ready — full registry readiness. The constraint that puts on a tenant
module is therefore narrower than "no model access": it must not depend on
any OTHER app's ready() side effects having already run. A tenant whose
services/student_profile_form.py is missing or broken therefore fails at
container boot, not with a 500 on the profile page — that changes how you'd
debug it, since the error surfaces at startup, in the autodiscover_modules
chain, not on first request to the profile view.

Settings-driven field ordering and relabelling are on MetaFormMixin
(cis/forms/utils.py), shared with the spec-driven application form.
"""
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from cis.models.customuser import CustomUser
from cis.services.tenant_services import get_tenant_service

_TENANT_MODULE = 'student_profile_form'


def _tenant_module():
    """The tenant's field-set module. Resolved per call; importlib caches."""
    return get_tenant_service(_TENANT_MODULE)


def tenant_editable_fields():
    """The tenant's post-SIS editable default, as a tuple.

    Falls back to () — nothing editable — when a tenant module omits the
    export. Fails safe: defaulting to the full profile set would silently
    reopen identity fields on applications already sent to the SIS.
    """
    return tuple(getattr(_tenant_module(), 'EDITABLE_FIELDS', ()) or ())


def tenant_ce_hidden_fields():
    """Extra fields the tenant hides from the CE-admin form, as a tuple.

    CISProfileMixin already drops the generic three (the SSN confirmation and
    the two password halves). Anything beyond that is a statement about which
    fields THIS tenant collects — sccc hides its SSN opt-out and its three
    agreement checkboxes, because a CE staffer entering a record on a student's
    behalf cannot agree on the student's behalf. Naming those in `cis` would
    put tenant field data back into the shared code this seam exists to keep
    empty of it.

    Absent export -> (): the tenant hides nothing extra, which is exactly the
    behaviour every tenant had before this seam existed. Note the default is
    the opposite kind of choice from tenant_editable_fields() above — there,
    empty is the restrictive answer and so the safe one; here, empty is the
    permissive answer, and it is safe because cis cannot know that a field a
    tenant does collect should be withheld from its own staff.
    """
    return tuple(getattr(_tenant_module(), 'CE_HIDDEN_FIELDS', ()) or ())


class EditableProfileMixin:
    """Post-SIS editable profile: restrict the field set by application status.

    A gated field is rendered READ-ONLY rather than dropped, so a student can
    see what is on file without being able to change it. Three consequences are
    handled deliberately, and all three are load-bearing:

    * The field is excluded from `save()` (see `readonly_fields`, honoured by
      `MetaFormMixin._save_fields_to_models`). Dropping the field used to give
      this for free; keeping it means a hand-crafted POST would otherwise reach
      the model.
    * `required` is cleared. Django enforces `required` on a disabled field
      using `initial`, so a required gated field with nothing on file would make
      the form permanently unsubmittable.
    * Field errors on gated fields are discarded in `full_clean`. The tenant's
      cross-field `clean()` sees the whole form, and an error on a value the
      student cannot edit is not actionable.

    Ordering matters — this must precede the tenant form in the MRO so its
    __init__ runs after the tenant form has built self.fields.
    """

    #: Not rendered at all when they are not editable — not even read-only. A
    #: disabled input still puts the value on the page, which for an SSN is an
    #: exposure rather than a convenience, and `verify_student_ssn` holds no
    #: stored value so it would render as an empty "re-enter SSN" box. The
    #: signup mechanics (password/confirm_password/signature) are stripped
    #: unconditionally further down and never reach this list.
    HIDE_WHEN_NOT_EDITABLE = ('ssn', 'verify_student_ssn')

    def __init__(self, *args, **kwargs):
        is_locked = kwargs.pop('is_locked', False)
        super().__init__(*args, **kwargs)

        student = kwargs.get('student') or (args[0] if args else None)
        self.student = student

        from cis.settings.student_profile import (
            SIGNUP_MECHANIC_FIELDS, profile_fields, student_profile,
        )

        # Signup mechanics never belong on the editable profile form.
        for field in SIGNUP_MECHANIC_FIELDS:
            if field in self.fields:
                del self.fields[field]

        status = getattr(student, 'application_status', None) if student else None

        # An in-review application is fully locked regardless of the caller.
        if status == 'in_review':
            is_locked = True

        if status == 'accepted':
            # Accepted: restrict to the admin-configured subset, and nothing
            # else. An empty configured list is honored (nothing editable);
            # only a missing setting row falls back to the tenant default.
            #
            # This deliberately does NOT widen the set for a student whose
            # record has not yet reached the SIS. It used to append
            # first_name / last_name / date_of_birth / ssn in that case, which
            # silently overrode the admin's exclusion of them — an accepted
            # student saw 32 fields where 29 were configured, and no amount of
            # unchecking boxes in the settings UI could close the gap. The
            # configured list is the only authority here. A tenant that wants
            # identity fields editable post-acceptance marks them editable.
            config = student_profile.from_db()
            configured = config.get('editable_fields')
            editable = list(
                configured if configured is not None
                else tenant_editable_fields()
            )
        else:
            # pending / draft (also student=None or any unrecognised status):
            # exactly the student-profile application fields — the fields a
            # student fills out when completing their application.
            editable = list(profile_fields())

        # A locked form has nothing editable at all, whether the lock came from
        # in_review or from the caller.
        if is_locked:
            editable = []

        #: Names rendered read-only by the gate. Distinct from `field.disabled`,
        #: which the tenant form also sets on its own account (`email` is
        #: declared disabled=True there) — only the names in this set are ones
        #: the *gate* froze, and only these are excluded from save.
        self.readonly_fields = set()

        for field_name in list(self.fields.keys()):
            if field_name in editable:
                continue
            if field_name in self.HIDE_WHEN_NOT_EDITABLE:
                del self.fields[field_name]
                continue
            field = self.fields[field_name]
            field.disabled = True
            field.required = False
            self.readonly_fields.add(field_name)

    def full_clean(self):
        super().full_clean()
        # Discard field errors the student cannot act on. The tenant's clean()
        # validates cross-field rules across the whole form — for example it
        # requires mailing_city/state/zip whenever same_as_permanent is falsy —
        # and a gated field's value came from the record, not the request. Left
        # in place, an incomplete record would make the profile permanently
        # unsubmittable. Non-field errors are deliberately NOT discarded: those
        # are not attributable to a single gated field, so swallowing them could
        # hide a real problem.
        for field_name in getattr(self, 'readonly_fields', ()):
            if self._errors:
                self._errors.pop(field_name, None)

    def clean_date_of_birth(self):
        # Not validating DOB in editable form
        return self.cleaned_data.get('date_of_birth')


class CISProfileMixin(forms.Form):
    """CE-admin profile: every field optional, all validation bypassed.

    CE staff are trusted to enter values the student-facing form would reject —
    past graduation dates, out-of-range DOBs. The extra admin FIELDS come from
    the tenant module's StudentCISExtraFields, which cis mixes in as a base;
    only `id` is declared here, being generic.

    Subclasses forms.Form for the same reason StudentCISExtraFields is mixed in
    as a real Form: DeclarativeFieldsMetaclass collects declared_fields only
    from bases that already have that attribute, so `id` would be dropped
    silently — with no error — off a plain mixin.
    """

    id = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Remove fields not needed for CIS users. The three below are generic —
        # an SSN confirmation and the two password halves are never a CE
        # staffer's to fill in. Beyond that it is the tenant's call, since it
        # depends on which fields that tenant collects at all.
        fields_to_remove = (['verify_student_ssn', 'password', 'confirm_password']
                            + list(tenant_ce_hidden_fields()))
        for field_name in fields_to_remove:
            if field_name in self.fields:
                del self.fields[field_name]

        # Make all fields optional for CIS users and strip browser-side
        # HTML5 validation attrs so CE staff can set values outside the
        # default min/max bounds (e.g. past graduation dates).
        for field in self.fields.values():
            field.required = False
            for attr in ('min', 'max', 'pattern', 'minlength', 'maxlength'):
                field.widget.attrs.pop(attr, None)

        # Enable email editing
        if 'email' in self.fields:
            self.fields['email'].disabled = False

        # Populate admin fields
        if self.student:
            user = self.student.user
            self.initial['id'] = self.student.id
            self.initial['psid'] = user.psid
            self.initial['alt_username'] = user.alt_username
            self.initial['secondary_email'] = user.secondary_email

    def clean_email(self):
        """Override to allow existing email for the current user"""
        data = self.cleaned_data['email'].lower()

        if self.student:
            qs = CustomUser.objects.filter(
                Q(email=data) | Q(username=data) | Q(secondary_email=data)
            ).exclude(pk=self.student.user.id)

            if qs.exists():
                raise ValidationError(
                    _("This email is already registered in the system."),
                    code='invalid'
                )

        return data

    def _clean_fields(self):
        # CE staff edits bypass field validation: only normalize types via
        # to_python (so '' → None for FK/Date/etc.), skip Field.validate /
        # run_validators / clean_<name>.
        for name, bf in self._bound_items():
            field = bf.field
            value = bf.initial if field.disabled else bf.data
            try:
                if isinstance(field, forms.FileField):
                    value = field.clean(value, bf.initial)
                else:
                    value = field.to_python(value)
            except ValidationError:
                value = None
            self.cleaned_data[name] = value

    def _clean_form(self):
        # CE staff edits bypass cross-field validation.
        pass


# --------------------------------------------------------------------------
# Lazy resolution
# --------------------------------------------------------------------------

_DERIVED_MIXINS = {
    'StudentEditableForm': EditableProfileMixin,
    'StudentCISForm': CISProfileMixin,
}

# Extra forms.Form bases per derived name. These must be real Form classes:
# DeclarativeFieldsMetaclass collects declared_fields only from bases that
# already have that attribute, so Field instances on a plain mixin are dropped
# with no error at all.
_DERIVED_EXTRA_BASES = {
    'StudentCISForm': ('StudentCISExtraFields',),
}

_class_cache = {}


def _build(name):
    module = _tenant_module()
    bases = (_DERIVED_MIXINS[name],)
    bases += tuple(getattr(module, attr)
                   for attr in _DERIVED_EXTRA_BASES.get(name, ()))
    bases += (module.StudentProfileForm,)
    cls = type(name, bases, {'__module__': __name__})
    return cls


def __getattr__(name):
    """Resolve the profile forms from the tenant app on first access.

    StudentProfileForm is the tenant class verbatim. The other two are built by
    combining a cis behavior mixin with it, and cached — isinstance checks and
    Django's form-media caching both assume a stable class object.
    """
    if name == 'StudentProfileForm':
        return _tenant_module().StudentProfileForm
    if name in _DERIVED_MIXINS:
        if name not in _class_cache:
            _class_cache[name] = _build(name)
        return _class_cache[name]
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
