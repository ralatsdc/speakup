from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import path, include

from core import views as core_views
from communications.views import email_review
from members.forms import EmailAuthenticationForm

urlpatterns = [
    path("admin/", admin.site.urls),
    # Override the default login so members sign in by email. Must precede the
    # auth-urls include so this pattern (and reverse('login')) wins.
    path(
        "accounts/login/",
        LoginView.as_view(authentication_form=EmailAuthenticationForm),
        name="login",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("members.urls")),
    path("help/", core_views.help_page, name="help"),
    path("email/review/", email_review, name="email_review"),
    path("", core_views.landing_page, name="landing"),
    path("", include("meetings.urls")),
]

# In production WhiteNoise serves only static files; role-guide media uploads
# are private to first-time-email attachments and never need a public URL.
# Serve them in DEBUG only so officers can preview uploads locally.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
