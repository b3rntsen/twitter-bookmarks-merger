"""
URL configuration for processing app.
"""
from django.urls import path
from . import views

app_name = 'processing'

urlpatterns = [
    path('status/', views.processing_status, name='processing_status'),
    path('sse/stream/', views.sse_status_stream, name='sse_stream'),
    path('trigger-today/', views.trigger_today_jobs, name='trigger_today_jobs'),
    path('force-start-all/', views.force_start_all_jobs, name='force_start_all_jobs'),
    path('restart-failed/', views.restart_failed_jobs, name='restart_failed_jobs'),
    path('kill-all-jobs/', views.kill_all_jobs, name='kill_all_jobs'),
    path('delete-all-content/', views.delete_all_twitter_content, name='delete_all_twitter_content'),
    path('toggle-content-type/<str:content_type>/', views.toggle_content_type, name='toggle_content_type'),
    path('start-content-type/<str:content_type>/', views.start_content_type, name='start_content_type'),
    path('stop-content-type/<str:content_type>/', views.stop_content_type, name='stop_content_type'),
]

