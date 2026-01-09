"""
URL configuration for bookmarks project.

Routes:
- /accounts/ - OAuth callbacks (must be at root for Google)
- /new-gen/* - Django app (old web-test functionality)
- / - Static HTML served by nginx (not Django)
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # OAuth must stay at root for Google callback URLs
    path('accounts/', include('allauth.urls')),
    path('accounts/', include('accounts.urls')),

    # Django app moved to /new-gen/
    path('new-gen/admin/', admin.site.urls),
    path('new-gen/', include('bookmarks_app.urls')),
    path('new-gen/twitter/', include('twitter.urls')),
    path('new-gen/lists/', include('lists_app.urls')),
    path('new-gen/processing/', include('processing_app.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

