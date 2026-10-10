"""validate_email_placeholders: every malformed placeholder is caught."""
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from cis.services.access_request_review import ALL_PLACEHOLDERS, PLACEHOLDERS
from cis.validators import validate_email_placeholders

APPROVE = set(PLACEHOLDERS['approve'])
DENY = set(PLACEHOLDERS['deny'])


class PlaceholderValidatorTests(SimpleTestCase):
    def errors(self, text, allowed=APPROVE):
        try:
            validate_email_placeholders(text, allowed, known=ALL_PLACEHOLDERS)
        except ValidationError as exc:
            return exc.messages
        return []

    def test_valid_text_passes(self):
        for text in ('Hi {{name}}', 'Hi {{ name }} at {{highschool}}', 'No placeholders', '',
                     'Set it: {{password_reset_link}}'):
            with self.subTest(text=text):
                self.assertEqual(self.errors(text), [])

    def test_unknown_name_suggests_closest(self):
        self.assertEqual(self.errors('Hi {{nmae}}'),
                         ["{{nmae}} isn't a placeholder. Did you mean {{name}}?"])

    def test_unknown_name_without_close_match_lists_allowed(self):
        msg = self.errors('{{zzz}}')[0]
        self.assertTrue(msg.startswith("{{zzz}} isn't a placeholder. Use one of: "))
        self.assertIn('{{name}}', msg)

    def test_known_but_not_allowed_for_decision(self):
        self.assertEqual(
            self.errors('Link {{password_reset_link}}', allowed=DENY),
            ['{{password_reset_link}} can only be used in an approval email.'])

    def test_unclosed_and_extra_braces(self):
        self.assertEqual(self.errors('Hi {{name}'), ['Unclosed placeholder near "{{name}".'])
        self.assertEqual(self.errors('Hi {{name}}}'), ['Stray "}" near "{{name}}}".'])

    def test_single_braces(self):
        self.assertEqual(self.errors('Hi {name}'), ['Use double braces: {{name}} instead of {name}.'])

    def test_tags_and_filters_rejected(self):
        self.assertEqual(self.errors('{% if x %}hi{% endif %}'),
                         ['Only plain placeholders like {{name}} are allowed here. Remove "{% ... %}".'])
        self.assertEqual(self.errors('{{name|upper}}'),
                         ['"{{name|upper}}" isn\'t allowed. Use a plain placeholder like {{name}}.'])

    def test_every_problem_listed(self):
        self.assertEqual(len(self.errors('{{nmae}} {name} {{role}')), 3)

    def test_spaces_inside_braces_ok(self):
        self.assertEqual(self.errors('{{   email   }}'), [])
