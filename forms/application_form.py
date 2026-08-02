"""Spec-driven student application form. Builds its field set from the tenant
spec (or a passed spec) using the cis field-type library, and reuses
MetaFormMixin to route initial/save by each field's storage_target.

Cross-field validation comes from the same spec: shared rules from the cis
registry (application_rules), plus the tenant's own validate() for anything cis
should not carry. Where the tenant declares ownership of a field, its validate()
replaces the shared rule covering that field rather than running alongside it.

Field ORDER and per-field WORDING are shared with the student profile: the spec
entry's `label` / `help_text` are the defaults, and anything configured for that
field name in `student_profile.field_messages()` overrides them, exactly as it
does for StudentProfileForm. So editing a field's Label in the profile-fields
settings table renames it on both form paths.
"""
from django import forms
from django.utils import timezone

from cis.forms.utils import MetaFormMixin
from cis.forms.application_fields import build_fields
from cis.forms.application_rules import get_rule, run_rules
from cis.forms.application_validators import apply_field_validators
from cis.forms.application_spec import (
    get_application_fields, get_application_rules, get_tenant_post_save,
    get_tenant_validator)


class SpecDrivenApplicationForm(MetaFormMixin, forms.Form):
    def __init__(self, spec=None, rules=None, student=None, request=None,
                 validator=None, post_save=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.student = student
        self.request = request

        # An explicit `spec` describes the WHOLE form, so the tenant's rules,
        # validator and post_save are not silently mixed into it. Only the
        # self-configuring form (spec=None) reads them from the tenant module;
        # get_application_form() passes all four together. Without this, every
        # cis test that builds a form from a literal spec would start picking
        # up the tenant's real config the day a tenant arms one.
        self_configuring = spec is None
        if self_configuring:
            spec = get_application_fields() or []
        if rules is None:
            rules = get_application_rules() if self_configuring else []
        self.rules = rules
        # Resolve every rule name now: a typo in tenant config must fail at
        # construction, not silently skip a validation rule at clean() time.
        for config in self.rules:
            get_rule(config['rule'])
        if validator is None and self_configuring:
            validator = get_tenant_validator()
        self._tenant_validate, self._tenant_owned_fields = (
            validator or (None, frozenset()))
        if post_save is None and self_configuring:
            post_save = get_tenant_post_save()
        self._tenant_post_save = post_save
        # Runtime state the field builders may need at construction time
        # (querysets, date bounds); see application_fields.build_fields.
        ctx = {'student': student, 'request': request}
        for entry in spec:
            for fname, field in build_fields(entry, ctx):
                self.fields[fname] = field
        # Default storage_path to the field name (mirrors StudentProfileForm.__init__),
        # so _populate_initial_from_instance / _save_fields_to_models resolve the model
        # attribute even when the spec entry gave no explicit `attr`.
        for field_name, field in self.fields.items():
            if hasattr(field, 'storage_target') and not getattr(field, 'storage_path', None):
                field.storage_path = field_name

        self._load_field_labels_from_db()

        if student is not None:
            self._populate_initial_from_instance(student)

        self._apply_field_weights(spec)

    def _apply_field_weights(self, spec):
        """Order the spec fields by the same student_profile weights the profile
        form uses, so a tenant configures display order once. A spec entry may
        carry its own `weight`, which wins for that field."""
        from cis.settings.student_profile import order_field_names, student_profile

        weights = dict(student_profile.field_weights())
        for entry in spec:
            if entry.get('weight') is not None:
                weights[entry['name']] = entry['weight']
        if not weights:
            return
        self.order_fields(order_field_names(list(self.fields), weights))

    def clean(self):
        # MetaFormMixin.clean applies the declarative copy_when syncing.
        cleaned_data = super().clean()

        # PT-20: sanitize up front, so an early return below cannot leave
        # markup in cleaned_data (mirrors StudentProfileForm.clean).
        self._sanitize_text_fields()
        cleaned_data = self.cleaned_data

        # Per-field validators/normalisers run FIRST, so the cross-field rules
        # below compare normalised values — otherwise fields_must_differ would
        # read '(509) 555-0147' and '+15095550147' as two different numbers.
        cleaned_data = apply_field_validators(self, cleaned_data)

        # Shared cross-field rules, minus any the tenant validator owns.
        run_rules(self, cleaned_data, self.rules,
                  owned_fields=self._tenant_owned_fields)

        # The escape hatch: whatever this tenant needs that cis should not
        # carry. It runs INSTEAD of the shared rules for the fields it owns.
        if self._tenant_validate:
            self._tenant_validate(self, cleaned_data)

        return cleaned_data

    def save(self, student=None, commit=True):
        # PT-20: the same choke point StudentProfileForm.save() runs. Without
        # it this form would be a second, unsanitized write path onto the very
        # records that gate protects.
        self._sanitize_text_fields()
        student = student or self.student
        user = getattr(student, 'user', None)
        data = self.cleaned_data

        # Snapshot before the write, so the dirty check below compares
        # like for like (see MetaFormMixin).
        tracked = self._dirty_tracked_field_names() if student else []
        before = (self._snapshot_fields(user, student, tracked)
                  if student else {})

        self._save_fields_to_models(user=user, student=student, commit=False)

        # The password is never a storage-routed field — `password_pair` marks
        # both halves 'skip' — so hashing it is this method's job. Without it,
        # complete_signup would save the form and then log the student in with
        # an unusable password.
        if user is not None and data.get('password'):
            user.set_password(data['password'])

        if student is not None:
            self._apply_derived_values(student, data)

        # The tenant's save-side escape hatch, for writes no storage target can
        # express. Runs before the commit below (so its writes persist) and
        # before the dirty check (so they count as a change).
        if self._tenant_post_save and student is not None:
            self._tenant_post_save(self, student, commit=False)

        if student is not None and self._is_self_edit(student):
            if before != self._snapshot_fields(user, student, tracked):
                student.profile_dirty_at = timezone.now()

        if commit:
            if user is not None:
                user.save()
            if student is not None:
                student.save()

        return student

    def _apply_derived_values(self, student, data):
        """The two writes StudentProfileForm.save() makes that are cis model
        logic rather than tenant policy, so the engine carries them rather than
        every tenant re-deriving them.

        Anything genuinely tenant-shaped (sccc's signed_no_ssn_waiver, ewu's
        new-highschool handling) belongs in the tenant's post_save instead.
        """
        from cis.utils import active_term

        student.profile_last_reviewed = active_term()

        if not data.get('graduation_date'):
            return

        computed = student.get_grade_level(graduation_date=data['graduation_date'])
        # get_grade_level may return out-of-domain sentinels ('GRAD', '--',
        # None) that aren't valid choices and would overflow the column; in
        # those cases keep the student's own current selection.
        valid = {code for code, _ in
                 student._meta.get_field('grade_level').choices if code}
        if computed in valid:
            student.grade_level = computed


def get_application_form(student=None, request=None, data=None):
    """Return the tenant's application form: spec-driven when a tenant spec
    exists, else the legacy StudentProfileForm (ewu path — unchanged)."""
    from cis.forms.student_profile import StudentProfileForm
    spec = get_application_fields()
    if spec:
        # Pass the tenant's whole configuration together — the form only
        # self-resolves it when built with no spec at all.
        return SpecDrivenApplicationForm(
            spec=spec, rules=get_application_rules(),
            validator=get_tenant_validator(),
            post_save=get_tenant_post_save(),
            student=student, request=request, data=data)
    return StudentProfileForm(student=student, request=request, data=data)
