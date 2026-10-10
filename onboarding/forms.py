from django import forms
from .models import ClientIntakeSubmission

class ClientIntakeForm(forms.ModelForm):
    class Meta:
        model = ClientIntakeSubmission
        fields = [
            'company_legal_name',
            'tax_id',
            'billing_contact_name',
            'billing_contact_email',
            'billing_address',
            'primary_use_case',
            'target_launch_date',
            'technical_contact_name',
            'technical_contact_email',
            'privacy_consent_given',
        ]
        widgets = {
            'company_legal_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Acme Corporation LLC'}),
            'tax_id': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. 12-3456789'}),
            'billing_contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'}),
            'billing_contact_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'billing@company.com'}),
            'billing_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Street Address, City, State, ZIP, Country'}),
            'primary_use_case': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Describe your primary project objectives...'}),
            'target_launch_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'technical_contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Technical Lead Name'}),
            'technical_contact_email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'tech@company.com'}),
            'privacy_consent_given': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_privacy_consent_given(self):
        consent = self.cleaned_data.get('privacy_consent_given')
        if not consent:
            raise forms.ValidationError("You must accept the terms and privacy acknowledgement to proceed.")
        return consent
