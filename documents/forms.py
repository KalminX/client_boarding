import os
from django import forms
from django.conf import settings
from .models import Document

class DocumentUploadForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ['file', 'document_type_hint']
        widgets = {
            'file': forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.txt,.csv,.json,.png,.jpg,.jpeg'}),
            'document_type_hint': forms.Select(
                choices=[
                    ('general', 'General Document'),
                    ('tax_form', 'W-9 / Tax ID Certificate'),
                    ('id_proof', 'Authorized Signatory ID'),
                    ('bank_details', 'Banking / ACH Form'),
                    ('incorporation', 'Articles of Incorporation'),
                ],
                attrs={'class': 'form-select'}
            ),
        }

    def clean_file(self):
        uploaded_file = self.cleaned_data.get('file')
        if not uploaded_file:
            raise forms.ValidationError("Please select a file to upload.")

        # File size check
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE_BYTES', 10 * 1024 * 1024)
        if uploaded_file.size > max_size:
            raise forms.ValidationError(f"File size exceeds limit of {max_size // (1024 * 1024)}MB.")

        # Extension check
        allowed_exts = getattr(settings, 'ALLOWED_DOCUMENT_EXTENSIONS', ['.pdf', '.txt', '.csv', '.json', '.png', '.jpg', '.jpeg'])
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in allowed_exts:
            raise forms.ValidationError(f"Unsupported file type '{ext}'. Allowed extensions: {', '.join(allowed_exts)}.")

        return uploaded_file


class DocumentReviewForm(forms.Form):
    action = forms.ChoiceField(choices=[('approve', 'Approve Document'), ('reject', 'Reject Document')], widget=forms.RadioSelect)
    review_notes = forms.CharField(widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}), required=False)
