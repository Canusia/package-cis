from cis.utils import get_field


class ReportDataSourceMixin:
    """Make a report form usable as a bulk-mailer datasource that exposes ALL of
    its declared fields as ``{{shortcode}}`` tokens.

    A report mixes this in and declares:
        datasource_fields: dict   # {shortcode_token: 'dotted.attr.path'}; tokens
                                  #   must be valid template vars (no spaces/dots)
                                  #   and MUST include the email + name tokens.
        email_column: str         # token in datasource_fields holding the email
        name_columns: list[str]   # token(s) forming the recipient name
        datasource_descriptor: str
    and implements:
        recipient_queryset(self, data) -> iterable of model records

    The mixin derives recipient_columns()/get_recipients()/sample_row() so the
    bulk-mailer shows every token as a shortcode, renders each recipient's values
    for those tokens, and previews them.
    """

    use_as_datasource = True
    datasource_fields = {}
    email_column = 'email'
    name_columns = ['FirstName', 'LastName']
    datasource_descriptor = ''

    def recipient_queryset(self, data):
        raise NotImplementedError(
            'Report datasources must implement recipient_queryset(self, data).')

    def recipient_columns(self):
        """data_columns for the adapter: values are the shortcode tokens shown
        in the bulk-message editor."""
        return {token: token for token in self.datasource_fields}

    def _resolve(self, record, path):
        value = get_field(record, path)
        if callable(value):          # get_field returns bound methods uncalled
            value = value()
        return value

    def get_recipients(self, data):
        """Deduped recipient rows keyed by every declared token; email as a list."""
        email_path = self.datasource_fields[self.email_column]
        rows = []
        seen = set()
        for record in self.recipient_queryset(data):
            email = str(self._resolve(record, email_path) or '').strip()
            if not email or email in seen:
                continue
            seen.add(email)
            row = {token: self._resolve(record, path)
                   for token, path in self.datasource_fields.items()}
            row[self.email_column] = [email]   # bulk-mailer expects a list
            rows.append(row)
        return rows

    def sample_row(self):
        """Preview placeholders — one per shortcode token."""
        sample = {token: '{' + token + '}' for token in self.datasource_fields}
        sample[self.email_column] = 'sample@example.com'
        return sample
