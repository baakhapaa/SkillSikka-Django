"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import re

from django.conf import settings
from django.conf.urls.static import static
from django.http import Http404
from django.urls import include, path, re_path

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.api_views import InstructorRegistrationAPIView, StudentRegistrationAPIView


def _not_found(request):
    raise Http404

urlpatterns = [
    path('', include('core.urls')),
    path('api/register/student/', StudentRegistrationAPIView.as_view(), name='api-register-student-unversioned'),
    path('api/register/instructor/', InstructorRegistrationAPIView.as_view(), name='api-register-instructor-unversioned'),
    path('api/v1/', include('core.api_urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

# nginx serves /media/ in deployment; this covers runserver. No-op unless DEBUG.
# Verification documents stay private here too, as in nginx.conf.
if getattr(settings, 'MEDIA_URL', None):
    urlpatterns += [
        re_path(
            r'^%sverification-documents/' % re.escape(settings.MEDIA_URL.lstrip('/')),
            _not_found,
        ),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)