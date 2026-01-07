from django import forms
from .models import TwitterProfile


class TwitterConnectionForm(forms.ModelForm):
    """Form for connecting Twitter account."""
    username = forms.CharField(
        max_length=100,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Twitter username (without @)'
        })
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password (optional if using cookies)'
        }),
        help_text="Leave blank if you're providing session cookies"
    )
    use_cookies = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Use session cookies instead of password"
    )
    cookies_json = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 5,
            'placeholder': 'Paste session cookies as JSON (optional)'
        }),
        help_text="Paste cookies as JSON if you have them"
    )

    class Meta:
        model = TwitterProfile
        fields = []

    def clean(self):
        cleaned_data = super().clean()
        use_cookies = cleaned_data.get('use_cookies')
        password = cleaned_data.get('password')
        cookies_json = cleaned_data.get('cookies_json')

        if not use_cookies and not password:
            raise forms.ValidationError("Either password or cookies must be provided.")

        if use_cookies and not cookies_json:
            raise forms.ValidationError("Cookies JSON is required when using cookies.")

        return cleaned_data

