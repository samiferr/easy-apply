from django import forms

#: Lumen's text field and checkbox. The styles live in static/src/input.css
#: (`.field-input`, `.field-checkbox`, `.field-file`) so a hand-written filter
#: control in a template and a Django widget are the same component.
TEXT_INPUT_CLASSES = "field-input"
CHECKBOX_CLASSES = "field-checkbox"
FILE_INPUT_CLASSES = "field-file"


class StyledFormMixin:
    """Applies consistent Tailwind classes to every widget on a form."""

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CHECKBOX_CLASSES)
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", TEXT_INPUT_CLASSES)
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", TEXT_INPUT_CLASSES)
                widget.attrs.setdefault("rows", 4)
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault("class", FILE_INPUT_CLASSES)
            else:
                widget.attrs.setdefault("class", TEXT_INPUT_CLASSES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    pass


class StyledForm(StyledFormMixin, forms.Form):
    pass
