from uuid import uuid4

from django import forms
from django.db.models import Q

from .models import DocumentCategory


class DocumentUploadForm(forms.Form):
    upload_token = forms.UUIDField(widget=forms.HiddenInput)
    category = forms.ModelChoiceField(queryset=DocumentCategory.objects.none(), label="文档分类")
    title = forms.CharField(label="标题", max_length=250)
    description = forms.CharField(
        label="说明",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    document_date = forms.DateField(
        label="文档日期",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    file = forms.FileField(label="文件")

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = DocumentCategory.objects.filter(
            Q(project__isnull=True) | Q(project=project),
            is_active=True,
        ).order_by("sort_order", "name", "code")
        if not self.is_bound and not self.initial.get("upload_token"):
            self.initial["upload_token"] = uuid4()


class ProjectDocumentCategoryForm(forms.ModelForm):
    class Meta:
        model = DocumentCategory
        fields = ("code", "name", "sort_order")
