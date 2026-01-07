from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.profile, name='profile'),
    path('auth-check/', views.auth_check, name='auth_check'),
]

