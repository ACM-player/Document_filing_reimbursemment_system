from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group

from .constants import SYSTEM_GROUP_NAMES
from .models import AccountStatus, User, UserProfile

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
        return status
