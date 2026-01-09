from django.urls import path
from . import views

urlpatterns = [
    path('profile/', views.profile, name='profile'),
    path('health/', views.health_check, name='health_check'),
    path('auth-check/', views.auth_check, name='auth_check'),
    path('user-info/', views.user_info, name='user_info'),
    path('admin/', views.admin_panel, name='admin_panel'),
    path('invite/', views.invite_user, name='invite_user'),
    path('invite/<str:token>/', views.accept_invitation, name='accept_invitation'),
    path('delete/<int:user_id>/', views.delete_user, name='delete_user'),
    path('delete-invitation/<int:invitation_id>/', views.delete_invitation, name='delete_invitation'),
]

