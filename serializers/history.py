import json
from rest_framework import serializers

# Fields never shown by a Change History endpoint, on any tracked model
# (package-cis#64). CustomUser no longer stores the first three in its history
# table; this is the second line, for older rows on tenants that have not
# migrated yet and for any model that later adds a field of the same name.
SENSITIVE_HISTORY_FIELDS = frozenset({
    'password',
    'ssn',
    'last_login',
})


def history_field_is_hidden(name):
    return name in SENSITIVE_HISTORY_FIELDS


def visible_history_changes(record, prev):
    """``record.diff_against(prev).changes`` minus the sensitive fields."""
    delta = record.diff_against(prev, excluded_fields=SENSITIVE_HISTORY_FIELDS)
    return [c for c in delta.changes if not history_field_is_hidden(c.field)]


class HistorySerializer(serializers.Serializer):
    history_date = serializers.DateTimeField(format='%Y-%m-%dT%H:%M:%S')
    history_type = serializers.SerializerMethodField()
    history_user = serializers.SerializerMethodField()
    changes = serializers.SerializerMethodField()
    source_model = serializers.SerializerMethodField()
    value = serializers.SerializerMethodField()

    def get_history_type(self, obj):
        return {'+': 'Created', '~': 'Changed', '-': 'Deleted'}.get(
            obj.history_type, obj.history_type
        )

    def get_history_user(self, obj):
        if obj.history_user:
            name = obj.history_user.last_name
            if obj.history_user.first_name:
                name += f', {obj.history_user.first_name}'
            return name
        return 'System'

    def get_changes(self, obj):
        if obj.history_type == '+':
            return 'Record created'

        prev = obj.prev_record
        if not prev:
            # First tracked version of a record that predates history tracking:
            # there's no earlier version to diff against, so the column would
            # otherwise render blank. Label it instead.
            return 'Initial recorded version'

        parts = []
        for change in visible_history_changes(obj, prev):
            parts.append(f"{change.field}: \"{change.old}\" \u2192 \"{change.new}\"")
        return '; '.join(parts) if parts else 'No field changes'

    def get_source_model(self, obj):
        return getattr(obj, '_source_model', '')

    def get_value(self, obj):
        exclude = {'history_id', 'history_date', 'history_type', 'history_user_id', 'history_change_reason'}
        data = {
            k: str(v) for k, v in obj.__dict__.items()
            if not k.startswith('_') and k not in exclude
            and not history_field_is_hidden(k)
        }
        return json.dumps(data, indent=2)
