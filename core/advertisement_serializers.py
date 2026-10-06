from pathlib import Path
from urllib.parse import urlsplit
import warnings

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from .models import Advertisement


def validate_banner_image(upload):
    formats = {'.jpg': ('JPEG', 'image/jpeg'), '.jpeg': ('JPEG', 'image/jpeg'), '.png': ('PNG', 'image/png')}
    expected = formats.get(Path(upload.name).suffix.lower())
    if not expected:
        raise serializers.ValidationError('Use a JPG, JPEG, or PNG image.')
    if upload.size > 5 * 1024 * 1024:
        raise serializers.ValidationError('Image must not exceed 5 MiB.')
    if getattr(upload, 'content_type', None) != expected[1]:
        raise serializers.ValidationError('Image MIME type must match its extension and content.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            upload.seek(0)
            with Image.open(upload) as image:
                if image.format != expected[0]:
                    raise serializers.ValidationError('Image content does not match its extension and MIME type.')
                width, height = image.size
                if width > 8192 or height > 8192 or width * height > 20_000_000:
                    raise serializers.ValidationError('Image dimensions must not exceed 8192 per side or 20 million pixels.')
                image.verify()
            upload.seek(0)
            with Image.open(upload) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise serializers.ValidationError('Image is corrupt, truncated, or unsafe.')
    finally:
        upload.seek(0)
    return upload


class AdvertisementDisplaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Advertisement
        fields = ['id', 'title', 'description', 'banner_image', 'cta_text', 'cta_url', 'starts_at', 'ends_at', 'display_order']


class AdvertisementAdminSerializer(AdvertisementDisplaySerializer):
    banner_image = serializers.FileField(allow_empty_file=False)
    cta_url = serializers.URLField(max_length=2048, required=False, allow_blank=True)

    class Meta(AdvertisementDisplaySerializer.Meta):
        fields = AdvertisementDisplaySerializer.Meta.fields + ['is_active', 'archived_at', 'created_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'archived_at', 'created_by', 'created_at', 'updated_at']

    def validate_banner_image(self, upload):
        return validate_banner_image(upload)

    def validate_cta_url(self, value):
        if value and urlsplit(value).scheme.lower() not in {'http', 'https'}:
            raise serializers.ValidationError('CTA URL must use HTTP or HTTPS.')
        return value

    def validate(self, attrs):
        starts = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))
        if starts is not None and ends is not None and ends < starts:
            raise serializers.ValidationError({'ends_at': ['End time must not be earlier than start time.']})
        return attrs
