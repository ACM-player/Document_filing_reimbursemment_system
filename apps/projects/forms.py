from django import forms
from django.db.models import Q

from apps.accounts.constants import LAB_MEMBER_GROUP
from apps.accounts.models import AccountStatus, User

from .models import Project, ProjectAccessRequest, ProjectRole, ProjectStatus
from .permissions import editable_project_fields, is_system_admin


class ProjectCreateForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = (
            "project_code",
            "name",
            "short_name",
            "project_type",
            "status",
            "visibility",
            "start_date",
            "end_date",
            "description",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project_type"].queryset = self.fields["project_type"].queryset.filter(
            is_active=True
        )
        self.fields["status"].choices = [
            choice for choice in ProjectStatus.choices if choice[0] != ProjectStatus.ARCHIVED
        ]


class ProjectUpdateForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = (
            "project_code",
            "name",
            "short_name",
            "project_type",
            "status",
            "visibility",
            "principal_investigator",
            "start_date",
            "end_date",
            "description",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        allowed_fields = editable_project_fields(actor, self.instance)
        for field_name in tuple(self.fields):
            if field_name not in allowed_fields:
                self.fields.pop(field_name)

        if "project_type" in self.fields:
            self.fields["project_type"].queryset = self.fields["project_type"].queryset.filter(
                Q(is_active=True) | Q(pk=self.instance.project_type_id)
            )
        if "status" in self.fields and not is_system_admin(actor):
            self.fields["status"].choices = [
                choice for choice in ProjectStatus.choices if choice[0] != ProjectStatus.ARCHIVED
            ]
        if "principal_investigator" in self.fields:
            self.fields["principal_investigator"].queryset = User.objects.filter(
                account_status=AccountStatus.ACTIVE,
                groups__name=LAB_MEMBER_GROUP,
            ).distinct()


class ProjectMemberForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.none(), label="用户")
    role = forms.ChoiceField(
        label="项目角色",
        choices=[
            (ProjectRole.MANAGER, ProjectRole.MANAGER.label),
            (ProjectRole.MEMBER, ProjectRole.MEMBER.label),
            (ProjectRole.VIEWER, ProjectRole.VIEWER.label),
        ],
    )

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = (
            User.objects.filter(
                account_status=AccountStatus.ACTIVE,
                groups__name=LAB_MEMBER_GROUP,
            )
            .exclude(pk=project.principal_investigator_id)
            .distinct()
        )


class AccessRequestForm(forms.ModelForm):
    class Meta:
        model = ProjectAccessRequest
        fields = ("reason",)
        widgets = {"reason": forms.Textarea(attrs={"rows": 4})}


class AccessReviewForm(forms.Form):
    decision = forms.ChoiceField(
        label="处理结果",
        choices=(("approve", "批准"), ("reject", "拒绝")),
    )
    review_note = forms.CharField(
        label="审核说明",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    expires_at = forms.DateTimeField(
        label="访问到期时间",
        required=False,
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={"type": "datetime-local"},
        ),
    )

    def clean(self):
        cleaned_data = super().clean()
        if (
            cleaned_data.get("decision") == "reject"
            and not cleaned_data.get("review_note", "").strip()
        ):
            self.add_error("review_note", "拒绝申请时必须填写原因。")
        return cleaned_data
