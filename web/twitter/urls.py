from django.urls import path
from . import views

app_name = 'twitter'

urlpatterns = [
    path('connect/', views.connect_twitter, name='connect'),
    path('disconnect/', views.disconnect_twitter, name='disconnect'),
    path('sync/', views.sync_bookmarks, name='sync'),
    path('sync-status/', views.bookmark_sync_status, name='bookmark_sync_status'),
]

