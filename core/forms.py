from django import forms

#: Tonal's outlined text field: the `outline` role (3:1 on every surface) is the
#: only thing that identifies an input as a control, and focus thickens it to a
#: 2px `primary` border. Placeholders use `on-surface-variant`, which clears 4.5:1
#: because they often carry the format hint.
TEXT_INPUT_CLASSES = (
    "block w-full rounded-tn-xs border border-outline bg-transparent px-4 py-3 text-base "
    "text-on-surface placeholder:text-on-surface-variant transition "
    "hover:border-on-surface focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary "
)

CHECKBOX_CLASSES = (
    "h-[18px] w-[18px] rounded-[2px] border-2 border-on-surface-variant bg-transparent text-primary "
    "focus:ring-2 focus:ring-secondary"
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
                    "block w-full text-sm text-on-surface-variant file:mr-4 file:rounded-lg "
                    "file:border-0 file:bg-primary-container file:px-4 file:py-2 file:text-sm "
                    "file:font-semibold file:text-primary hover:file:bg-primary-container "
                    "",
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
