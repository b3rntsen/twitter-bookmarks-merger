"""
URL configuration for lists app.
"""
from django.urls import path
from . import views

app_name = 'lists'

urlpatterns = [
    path('', views.list_selection, name='list_selection'),
    path('delete-all/', views.delete_all_lists, name='delete_all_lists'),
    path('<int:list_id>/events/', views.list_events, name='list_events'),
    path('<int:list_id>/sync/', views.sync_list_tweets, name='sync_list_tweets'),
    path('<int:list_id>/generate-events/', views.generate_events, name='generate_events'),
    path('<int:list_id>/status/', views.list_status, name='list_status'),
    path('<int:list_id>/delete/', views.delete_list, name='delete_list'),
]
