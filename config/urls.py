from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from core import views as core_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("help/", core_views.help_page, name="help"),
    path("", core_views.landing_page, name="landing"),
    path("", include("meetings.urls")),
]

# In production WhiteNoise serves only static files; role-guide media uploads
# are private to first-time-email attachments and never need a public URL.
# Serve them in DEBUG only so officers can preview uploads locally.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
