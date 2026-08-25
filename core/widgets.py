"""Form widgets shared across apps."""

from django import forms
from django.templatetags.static import static

# The vendored picker and its emoji dataset. Both are served from our own
# origin: the library's stock ``dataSource`` points at jsdelivr, and a page
# that falls back to it breaks -- silently, as an empty picker -- on any
# network that filters third-party CDNs. See CLAUDE.md, "Frontend".
PICKER_JS = "core/vendor/emoji-picker-element/picker.js"
PICKER_DATA = "core/vendor/emoji-picker-element/data.json"


class EmojiPickerMixin:
    """Marks a text widget for the emoji button added by ``emoji-field.js``.

    The asset URLs are attached per-field rather than baked into the script
    because ``ManifestStaticFilesStorage`` hashes them in production, so only
    the staticfiles machinery knows the real paths. They are resolved here at
    render time rather than at import time: a module-level ``static()`` call
    would hit the manifest while Django is still importing, which fails on a
    fresh checkout that has not run ``collectstatic`` yet.
    """

    class Media:
        css = {"all": ("core/emoji-field.css",)}
        js = ("core/emoji-field.js",)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget_attrs = context["widget"]["attrs"]
        widget_attrs["data-emoji"] = True
        widget_attrs["data-emoji-picker-src"] = static(PICKER_JS)
        widget_attrs["data-emoji-data-src"] = static(PICKER_DATA)
        return context


class EmojiTextInput(EmojiPickerMixin, forms.TextInput):
    """Single-line text input with an emoji button."""


class EmojiTextarea(EmojiPickerMixin, forms.Textarea):
    """Textarea with an emoji button."""
