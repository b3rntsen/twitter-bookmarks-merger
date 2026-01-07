from django.urls import path
from . import views
from django.views.generic import RedirectView

urlpatterns = [
    path('', views.bookmark_list, name='bookmark_list'),
    path('bookmark/<str:tweet_id>/', views.bookmark_detail, name='bookmark_detail'),
    path('bookmark/<str:tweet_id>/delete/', views.delete_bookmark, name='delete_bookmark'),
    path('bookmark/<str:tweet_id>/html/', views.view_html, name='view_html'),
    path('bookmark/<str:tweet_id>/pdf/preview/', views.preview_pdf, name='preview_pdf'),
    path('bookmark/<str:tweet_id>/pdf/', views.download_pdf, name='download_pdf'),
    path('delete-all/', views.delete_all_bookmarks, name='delete_all_bookmarks'),
    path('curated-feed/', views.curated_feed, name='curated_feed'),
    path('media/tweets/<str:tweet_id>/<str:filename>', views.serve_video, name='serve_video'),
]

