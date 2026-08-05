from django import forms
from django.conf import settings
from django.forms import ModelForm
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _


def with_meta(field, *, target, path=None, validate=None, depends_on=None, copy_when=None):
    """
    Attach storage and validation metadata to a Django form field.

    Args:
        field: A Django form field instance
        target: Storage target string ('user', 'student', 'meta',
                'notifications', 'skip')
                - 'user': save to CustomUser model
                - 'student': save to Student model
                - 'meta': save to Student.meta JSON field
                - 'notifications': save to Student.notifications JSON field
                  (contact preferences — cell_phone_opt_in and friends)
                - 'skip': validation only, not saved
        path: Attribute/key name on target model (defaults to field name)
        validate: Dict of client-side validation rules, injected as data-validate-* attrs
                  Supported: required, min-length, max-length, pattern, match, message
        depends_on: Dict for conditional visibility with keys:
                    - field: controller field name
                    - value: expected value(s), comma-separated for multiple
                    - negate: (optional) bool, show when value does NOT match
        copy_when: Dict for declarative field-to-field data syncing with keys:
                    - trigger: checkbox/boolean field name that enables the copy
                    - source: the field name to copy data from

    Returns:
        The field with metadata attached

    Examples:
        first_name = with_meta(
            forms.CharField(max_length=128),
            target='user',
            validate={'required': 'true', 'min-length': '2'},

            mailing_address = with_meta(
            forms.CharField(max_length=128),
            target='meta',
            copy_when={'trigger': 'same_as_permanent', 'source': 'permanent_address'}
        )
        )
    """
    # Attach storage metadata
    field.storage_target = target
    field.storage_path = path  # Will default to field name in form's __init__

    # Inject validation attrs into widget
    if validate:
        for rule, value in validate.items():
            field.widget.attrs[f'data-validate-{rule}'] = value

    # Inject conditional visibility attrs into widget
    if depends_on:
        field.widget.attrs['data-depends-on'] = depends_on.get('field', '')
        field.widget.attrs['data-depends-value'] = depends_on.get('value', '')
        if depends_on.get('negate'):
            field.widget.attrs['data-depends-negate'] = 'true'
    if copy_when:
        field.copy_trigger = copy_when.get('trigger')
        field.copy_source = copy_when.get('source')
        
        # Inject into HTML so your frontend JS can automatically hide/show them
        # this would give control of hide and reveal to with_meta but I decided to leave that for now
        # field.widget.attrs['data-copy-trigger'] = field.copy_trigger
        # field.widget.attrs['data-copy-source'] = field.copy_source

    return field


class MetaFormMixin:
    """
    Mixin for forms using with_meta field declarations.

    Provides generic __init__ population and save methods that use
    field metadata to read/write from appropriate models.
    """

    # PT-20: free-text values are stripped of markup before they are persisted
    # (and on clean), so stored values later rendered via Student.asHTML|safe
    # can never carry markup. Passwords are excluded — they are hashed, never
    # rendered, and must persist exactly as entered.
    SANITIZE_EXCLUDED_FIELDS = frozenset({'password', 'confirm_password'})

    def _sanitize_text_fields(self):
        """Strip HTML/markup from every free-text value in cleaned_data.

        Lives on the mixin so every with_meta form gets it — StudentProfileForm
        and its descendants, and the spec-driven application form, which would
        otherwise be an unsanitized second write path onto the same records.

        Generic: covers all current and future fields, not an allowlist.
        Non-string values and excluded fields (passwords) pass through
        untouched. Operates in place on cleaned_data; safe to call without
        full validation (used in tests)."""
        from cis.utils import sanitize_plain_text

        for name, value in list(self.cleaned_data.items()):
            if name in self.SANITIZE_EXCLUDED_FIELDS:
                continue
            if isinstance(value, str):
                self.cleaned_data[name] = sanitize_plain_text(value)
        return self.cleaned_data

    # ------------------------------------------------------------------
    # profile_dirty_at tracking
    #
    # Shared by both form paths: the flag exists so CE staff can review a
    # change a *student* made to their own record, which is a property of the
    # request and the cis `student_profile` setting, not of any tenant's field
    # list. Kept here so the spec-driven form cannot silently drop it.
    # ------------------------------------------------------------------

    def _is_self_edit(self, student):
        """True when the request is the student updating their own record."""
        request = getattr(self, 'request', None)
        if request is None or not getattr(request, 'user', None):
            return False
        return request.user.is_authenticated and request.user.id == student.user_id

    def _dirty_tracked_field_names(self):
        """Subset of the profile-field vocabulary admins have marked editable.
        Falls back to the whole vocabulary when no setting row exists."""
        from cis.settings.student_profile import profile_fields, student_profile
        config = student_profile.from_db()
        configured = config.get('editable_fields')
        return list(configured if configured is not None else profile_fields())

    def _snapshot_fields(self, user, student, field_names):
        """Return current values for the named form fields.

        Values are deep-copied so that mutations to ``student.meta`` during
        ``_save_fields_to_models`` cannot alias the pre-save snapshot. Lookup
        order: user attr, then student attr, then ``student.meta`` key.
        Unknown fields are silently skipped (the configured editable set can
        outgrow form vocabulary).
        """
        import copy
        snap = {}
        meta = student.meta or {}
        for name in field_names:
            if hasattr(user, name):
                snap[name] = copy.deepcopy(getattr(user, name))
            elif hasattr(student, name):
                snap[name] = copy.deepcopy(getattr(student, name))
            elif name in meta:
                snap[name] = copy.deepcopy(meta[name])
        return snap

    # ------------------------------------------------------------------
    # Settings-driven field ordering and wording
    #
    # Neither method names a field: they reorder and relabel whatever fields
    # the form has, from the `student_profile` setting. Kept here so tenants
    # never carry a copy and so the spec-driven application form is ordered
    # and worded by the same config as the legacy profile form.
    # ------------------------------------------------------------------

    def apply_field_weights(self):
        """Reorder the form's fields by the admin-configured weights on the
        student_profile setting. A missing/blank config leaves order untouched."""
        from cis.settings.student_profile import order_field_names, student_profile

        weights = student_profile.field_weights()
        if not weights:
            return
        self.order_fields(order_field_names(list(self.fields), weights))

    def _load_field_labels_from_db(self):
        """Load dynamic labels/help_text from the student_profile setting
        (falling back to the legacy signup blob inside field_messages()).

        The stored text is marked safe but is NOT rendered as a Django
        template: `validate_html_short_code` runs on it at *save* time only, to
        catch broken `{% %}` syntax before it can reach the student-facing
        form. So a `{{ var }}` written into a label or help text is displayed
        literally rather than interpolated — HTML is the only markup that has
        any effect here (help text legitimately carries HTML, e.g. the
        highschool_not_listed checkbox).
        """
        from cis.settings.student_profile import student_profile

        form_labels = student_profile.field_messages()

        for field_name, field in self.fields.items():
            field_attr = form_labels.get(field_name) or {}
            if field_attr.get('label'):
                field.label = mark_safe(field_attr['label'])
            if field_attr.get('help_text'):
                field.help_text = mark_safe(field_attr['help_text'])

    def apply_declarative_copies(self, cleaned_data):
        """Applies copy_when logic declaratively. Can be called multiple times."""
        for name, field in self.fields.items():
            if hasattr(field, 'copy_trigger'):
                trigger_val = cleaned_data.get(field.copy_trigger)
                
                # If the checkbox is checked, trigger the copy
                if trigger_val in [True, 'True', 'on']:
                    source_val = cleaned_data.get(field.copy_source)
                    
                    # 1. Inject the source data into this field
                    cleaned_data[name] = source_val
                    
                    # 2. Forgive Django's built-in "This field is required" error 
                    # since we just fulfilled the requirement dynamically
                    if hasattr(self, '_errors') and name in self._errors:
                        del self._errors[name]
        return cleaned_data

    def clean(self):
        """
        Generic clean step to handle declarative `copy_when` instructions
        before Django finalizes validation.
        """
        cleaned_data = super().clean()
        return self.apply_declarative_copies(cleaned_data)

    def _populate_initial_from_instance(self, student):
        """
        Populate form initial values from a student instance using field metadata.
        Call this from __init__ after super().__init__().
        """
        if not student:
            return

        for name, field in self.fields.items():
            target = getattr(field, 'storage_target', None)
            if not target or target == 'skip':
                continue

            path = getattr(field, 'storage_path', None) or name

            try:
                if target == 'user' and hasattr(student, 'user'):
                    value = getattr(student.user, path, '')
                elif target == 'student':
                    value = getattr(student, path, '')
                elif target == 'meta' and hasattr(student, 'meta') and student.meta:
                    value = student.meta.get(path, '')
                elif (target == 'notifications'
                        and getattr(student, 'notifications', None)):
                    value = student.notifications.get(path, '')
                else:
                    continue
            except AttributeError:
                continue

            # A blank instance value must not overwrite a declared `initial`.
            # BoundField.value() reads `form.initial.get(name, field.initial)`,
            # so writing the key at all makes the declaration lose -- and a
            # field only declares an initial because it wants one in exactly
            # this case. Fatal on a hidden required field: the control renders
            # empty, the POST carries nothing, and the student sees a
            # required-field error naming an input they cannot see (ewu#44).
            # An instance value that actually exists still wins.
            if value in (None, '') and field.initial not in (None, ''):
                continue

            self.initial[name] = value

    def _save_fields_to_models(self, user=None, student=None, commit=True):
        """
        Save cleaned_data to models based on field metadata.

        Args:
            user: CustomUser instance to update
            student: Student instance to update
            commit: Whether to call save() on models

        Returns:
            Tuple of (user, student) with updated values
        """
        readonly = getattr(self, 'readonly_fields', ())

        for name, field in self.fields.items():
            target = getattr(field, 'storage_target', None)
            if not target or target == 'skip':
                continue

            # Never persist a field the form marked read-only. The student
            # could not have changed it, and a disabled field's cleaned value
            # comes from `initial` — which is blank wherever initial population
            # did not find a value, so writing it back could erase data the
            # record actually holds. Forms that expose gated fields read-only
            # (EditableProfileMixin) rely on this; forms without the attribute
            # are unaffected.
            if name in readonly:
                continue

            path = getattr(field, 'storage_path', None) or name
            value = self.cleaned_data.get(name)

            # Check depends_on condition
            depends_on_field = field.widget.attrs.get('data-depends-on')
            if depends_on_field:
                depends_value = field.widget.attrs.get('data-depends-value', '')
                depends_negate = field.widget.attrs.get('data-depends-negate') == 'true'
                controller_value = str(self.cleaned_data.get(depends_on_field, ''))

                expected_values = [v.strip() for v in depends_value.split(',')]
                is_match = controller_value in expected_values

                if depends_negate:
                    is_match = not is_match

                if not is_match:
                    continue  # Skip this field, condition not met

            # Write to appropriate model
            if target == 'user' and user:
                setattr(user, path, value)
            elif target == 'student' and student:
                setattr(student, path, value)
            elif target == 'meta' and student:
                if not hasattr(student, 'meta') or student.meta is None:
                    student.meta = {}
                # Student.meta is a JSONField; date/datetime are not
                # JSON-serializable, so store them as ISO strings.
                import datetime as _dt
                if isinstance(value, (_dt.date, _dt.datetime)):
                    value = value.isoformat()
                student.meta[path] = value
            elif target == 'notifications' and student:
                # Same JSON treatment as meta, on the preferences blob.
                if getattr(student, 'notifications', None) is None:
                    student.notifications = {}
                import datetime as _dt
                if isinstance(value, (_dt.date, _dt.datetime)):
                    value = value.isoformat()
                student.notifications[path] = value

        if commit:
            if user:
                user.save()
            if student:
                student.save()

        return user, student

class EmailForm(forms.Form):
    """
    Generic form to collect email message
    """
    to = forms.CharField(
        required=True,
        widget=forms.TextInput
    )
    
    subject = forms.CharField(
        required=True,
        widget=forms.TextInput
    )

    message = forms.CharField(
        required=True,
        widget=forms.Textarea
    )

    def send(self):
        from django.core.mail import EmailMessage

        to = self.cleaned_data['to'].split(',')
        subject = self.cleaned_data['subject']
        message = self.cleaned_data['message']

        email = EmailMessage(
            subject,
            message,
            settings.MY_CE.get('default_from'),
            to,
            reply_to=[settings.MY_CE.get('default_from')]
        )
        return email.send(fail_silently=True)