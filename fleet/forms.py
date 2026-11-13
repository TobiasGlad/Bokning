import io
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.files.base import ContentFile
from django.utils import timezone
from .models import Resource, Booking, Issue, Maintenance


class ResourceForm(forms.ModelForm):
    class Meta:
        model = Resource
        exclude = ['lock_version', 'created_at']
        widgets = {'description': forms.Textarea(attrs={'rows': 3}), 'key_instructions': forms.Textarea(attrs={'rows': 2})}

    def clean_image(self):
        upload = self.cleaned_data.get('image')
        if not upload or not hasattr(upload, 'content_type'):
            return upload
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Bilden får vara högst 5 MB.')
        try:
            image = Image.open(upload)
            if image.width * image.height > 24_000_000:
                raise forms.ValidationError('Bilden är för stor. Välj en bild under 24 megapixel.')
            image = ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((1600, 1200))
            output = io.BytesIO()
            image.save(output, format='JPEG', quality=86)
            # Re-encode to strip metadata, active content and user-controlled file names.
            return ContentFile(output.getvalue(), name=uuid.uuid4().hex + '.jpg')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise forms.ValidationError('Välj en giltig bild (JPEG, PNG eller WebP).') from exc


class BookingForm(forms.Form):
    resource = forms.ModelChoiceField(label='Resurs', queryset=Resource.objects.filter(active=True))
    start = forms.DateTimeField(label='Från', input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    end = forms.DateTimeField(label='Till', input_formats=['%Y-%m-%dT%H:%M'], widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))
    purpose = forms.CharField(label='Ändamål / destination', max_length=240)
    notes = forms.CharField(label='Anteckning', required=False, widget=forms.Textarea(attrs={'rows': 2}))


class UserForm(UserCreationForm):
    email = forms.EmailField(label='E-post')
    first_name = forms.CharField(label='Förnamn', max_length=150)
    last_name = forms.CharField(label='Efternamn', max_length=150, required=False)
    is_staff = forms.BooleanField(label='Administratör', required=False)

    class Meta:
        model = get_user_model()
        fields = ['email', 'first_name', 'last_name', 'is_staff', 'password1', 'password2']

    def clean_email(self):
        value = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(email__iexact=value).exists():
            raise forms.ValidationError('E-postadressen används redan.')
        return value

    def save(self, commit=True):
        self.instance.username = self.cleaned_data['email']
        return super().save(commit)


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = ['description']
        widgets = {'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Vad har hänt och vad behöver åtgärdas?'})}


class MaintenanceForm(forms.ModelForm):
    start = BookingForm.base_fields['start'].__deepcopy__({})
    end = BookingForm.base_fields['end'].__deepcopy__({})
    class Meta:
        model = Maintenance
        fields = ['resource', 'start', 'end', 'reason']


class ReturnForm(forms.Form):
    mileage = forms.IntegerField(label='Mätarställning vid återlämning (km)', min_value=0)
