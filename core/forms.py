from django import forms

#: `line-strong` rather than a light grey: an input's outline is the only thing
#: identifying it as a control, so WCAG 1.4.11 wants it at 3:1 against the
#: surface. slate-300 managed 1.48:1. Placeholders clear 4.5:1 for the same
#: reason real text does — they often carry the format hint.
TEXT_INPUT_CLASSES = (
    "block w-full rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-sm "
    "text-slate-900 placeholder:text-slate-500 shadow-sm transition focus:border-brand-600 "
    "focus:outline-none focus:ring-2 focus:ring-brand-500/40 "
    "dark:text-slate-100 dark:placeholder:text-slate-400"
)

CHECKBOX_CLASSES = (
    "h-4 w-4 rounded border-line-strong bg-surface text-brand-600 "
    "focus:ring-2 focus:ring-brand-500/40"
)


class StyledFormMixin:
    """Applies consistent Tailwind classes to every widget on a form."""

    def _style_fields(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", CHECKBOX_CLASSES)
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", TEXT_INPUT_CLASSES + " pr-8")
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", TEXT_INPUT_CLASSES)
                widget.attrs.setdefault("rows", 4)
            elif isinstance(widget, forms.ClearableFileInput):
                widget.attrs.setdefault(
                    "class",
                    "block w-full text-sm text-slate-600 file:mr-4 file:rounded-lg "
                    "file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-sm "
                    "file:font-semibold file:text-brand-700 hover:file:bg-brand-100 "
                    "dark:text-slate-300",
                )
            else:
                widget.attrs.setdefault("class", TEXT_INPUT_CLASSES)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    pass


class StyledForm(StyledFormMixin, forms.Form):
    pass
