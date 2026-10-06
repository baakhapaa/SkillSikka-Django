import logging

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_views import SuperAdminRequiredMixin, _create_audit_log
from .advertisement_serializers import AdvertisementAdminSerializer, AdvertisementDisplaySerializer
from .models import Advertisement, advertisement_image_path


logger = logging.getLogger(__name__)


class AdvertisementListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AdvertisementDisplaySerializer

    def get_queryset(self):
        now = timezone.now()
        return Advertisement.objects.filter(is_active=True, archived_at__isnull=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now),
            Q(ends_at__isnull=True) | Q(ends_at__gte=now),
        ).order_by('display_order', 'id')


def advertisement_snapshot(advertisement):
    return {
        'title': advertisement.title, 'description': advertisement.description,
        'banner_image': advertisement.banner_image.name,
        'cta_text': advertisement.cta_text, 'cta_url': advertisement.cta_url,
        'starts_at': advertisement.starts_at.isoformat() if advertisement.starts_at else None,
        'ends_at': advertisement.ends_at.isoformat() if advertisement.ends_at else None,
        'display_order': advertisement.display_order, 'is_active': advertisement.is_active,
        'archived_at': advertisement.archived_at.isoformat() if advertisement.archived_at else None,
    }


class AdvertisementAdminBase(SuperAdminRequiredMixin, APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.check_super_admin(request)

    def write_advertisement(self, request, advertisement_id=None):
        storage = Advertisement._meta.get_field('banner_image').storage
        new_name = None
        try:
            with transaction.atomic():
                instance = None
                if advertisement_id is not None:
                    instance = get_object_or_404(Advertisement.objects.select_for_update(), pk=advertisement_id)
                    if instance.archived_at is not None:
                        raise ValidationError({'detail': 'Archived advertisements cannot be edited.'})
                before = advertisement_snapshot(instance) if instance else None
                old_name = instance.banner_image.name if instance else None
                serializer = AdvertisementAdminSerializer(instance, data=request.data, partial=instance is not None, context={'request': request})
                serializer.is_valid(raise_exception=True)
                upload = serializer.validated_data.pop('banner_image', None)
                extra = {}
                if upload is not None:
                    new_name = storage.save(advertisement_image_path(instance, upload.name), upload)
                    extra['banner_image'] = new_name
                if instance is None:
                    extra['created_by'] = request.user
                advertisement = serializer.save(**extra)
                after = advertisement_snapshot(advertisement)
                _create_audit_log(request, 'update' if instance else 'create', 'advertisement', advertisement.pk,
                                  advertisement.title, metadata={'before': before, 'after': after})
                if instance is not None and before['is_active'] != after['is_active']:
                    _create_audit_log(request, 'activate' if after['is_active'] else 'deactivate', 'advertisement',
                                      advertisement.pk, advertisement.title, metadata={'before': before, 'after': after})
                if new_name and old_name and old_name != new_name:
                    def remove_replaced_image():
                        if not Advertisement.objects.filter(banner_image=old_name).exists():
                            storage.delete(old_name)
                    transaction.on_commit(remove_replaced_image, robust=True)
            return Response(AdvertisementAdminSerializer(advertisement, context={'request': request}).data,
                            status=status.HTTP_200_OK if instance else status.HTTP_201_CREATED)
        except Exception:
            if new_name:
                try:
                    if not Advertisement.objects.filter(banner_image=new_name).exists():
                        storage.delete(new_name)
                except Exception:
                    logger.exception('Could not clean up failed advertisement upload %s', new_name)
            raise


class AdvertisementAdminListAPIView(AdvertisementAdminBase):
    def get(self, request):
        advertisements = Advertisement.objects.select_related('created_by').order_by('display_order', 'id')
        results = AdvertisementAdminSerializer(advertisements, many=True, context={'request': request}).data
        return Response({'count': len(results), 'results': results})

    def post(self, request):
        return self.write_advertisement(request)


class AdvertisementAdminDetailAPIView(AdvertisementAdminBase):
    def get(self, request, advertisement_id):
        advertisement = get_object_or_404(Advertisement, pk=advertisement_id)
        return Response(AdvertisementAdminSerializer(advertisement, context={'request': request}).data)

    def patch(self, request, advertisement_id):
        return self.write_advertisement(request, advertisement_id)

    def delete(self, request, advertisement_id):
        with transaction.atomic():
            advertisement = get_object_or_404(Advertisement.objects.select_for_update(), pk=advertisement_id)
            if advertisement.archived_at is None:
                before = advertisement_snapshot(advertisement)
                advertisement.archived_at = timezone.now()
                advertisement.is_active = False
                advertisement.save(update_fields=['archived_at', 'is_active', 'updated_at'])
                _create_audit_log(request, 'delete', 'advertisement', advertisement.pk, advertisement.title,
                                  metadata={'archived': True, 'before': before, 'after': advertisement_snapshot(advertisement)})
        return Response(status=status.HTTP_204_NO_CONTENT)
