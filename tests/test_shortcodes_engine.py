from django.test import RequestFactory, TestCase

from cis.shortcodes import render_shortcodes


class ShortcodeEngineTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")

    def _reg(self):
        def hello(request, context, **attrs):
            return f"HI:{attrs.get('name', '')}"
        return {"hello": hello}

    def test_passes_plain_html_through(self):
        out = render_shortcodes("<p>hi</p>", self.request, {}, registry={})
        self.assertEqual(out, "<p>hi</p>")

    def test_expands_registered_shortcode_with_attrs(self):
        out = render_shortcodes('a [hello name="bob"] b', self.request, {}, registry=self._reg())
        self.assertEqual(out, "a HI:bob b")

    def test_multiple_shortcodes(self):
        out = render_shortcodes("[hello][hello name=\"x\"]", self.request, {}, registry=self._reg())
        self.assertEqual(out, "HI:HI:x")

    def test_unknown_shortcode_becomes_comment(self):
        out = render_shortcodes("[nope]", self.request, {}, registry={})
        self.assertEqual(out, "<!-- unknown shortcode: nope -->")

    def test_handler_error_becomes_comment(self):
        def boom(request, context, **attrs):
            raise ValueError("x")
        out = render_shortcodes("[boom]", self.request, {}, registry={"boom": boom})
        self.assertEqual(out, "<!-- shortcode error: boom -->")

    def test_none_content_is_empty(self):
        self.assertEqual(render_shortcodes(None, self.request, {}, registry={}), "")
