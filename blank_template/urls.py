from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse


urlpatterns = [
    path('healthz/', lambda request: HttpResponse("ok", content_type="text/plain")),
    path('admin/', admin.site.urls),
    path('', include(('accounts.urls'), namespace='accounts')),
    path('api/', include('api.urls')),
]

handler404 = 'accounts.views.custom_404'

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
