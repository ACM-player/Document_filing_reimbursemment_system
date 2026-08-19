from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group

from .constants import SYSTEM_GROUP_NAMES
from .models import AccountStatus, User, UserProfile
from .services import PERMANENT_ACCOUNT_STATUSES, validate_user_status_transition

GENERIC_LOGIN_ERROR = "用户名或密码错误，或登录暂时受到限制。"


class LoginForm(AuthenticationForm):
    error_messages = {
        "invalid_login": GENERIC_LOGIN_ERROR,
        "inactive": GENERIC_LOGIN_ERROR,
    }


class SelfProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("display_name", "email")


class SelfProfileDetailsForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("department", "student_or_staff_id", "phone")


class LabArchiveUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "display_name", "email", "account_status")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = True
        if commit:
            user.save()
        return user


class LabArchiveUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "groups" in self.fields:
            self.fields["groups"].queryset = Group.objects.filter(name__in=SYSTEM_GROUP_NAMES)

    def clean_account_status(self):
        status = self.cleaned_data["account_status"]
        if self.instance.is_superuser and status != AccountStatus.ACTIVE:
            raise forms.ValidationError("不能通过管理后台禁用应急超级管理员。")
        if self.instance.pk:
            old_status = User.objects.only("account_status").get(pk=self.instance.pk).account_status
            try:
                validate_user_status_transition(old_status=old_status, new_status=status)
            except forms.ValidationError as error:
                raise forms.ValidationError(error.messages) from error
            if status in PERMANENT_ACCOUNT_STATUSES and old_status != status:
                from apps.projects.models import Project

                blocking_codes = list(
                    Project.all_objects.filter(
                        principal_investigator=self.instance,
                        deleted_at__isnull=True,
                    )
                    .order_by("project_code")
                    .values_list("project_code", flat=True)[:5]
                )
                if blocking_codes:
                    raise forms.ValidationError(
                        f"请先转移未软删除项目负责人：{'、'.join(blocking_codes)}。"
                    )
        return status
