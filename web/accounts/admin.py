from django.contrib import admin
from .models import UserProfile, Invitation


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'ai_provider', 'is_admin', 'created_at', 'updated_at')
    list_filter = ('ai_provider', 'is_admin', 'created_at')
    search_fields = ('user__email', 'user__username')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'invited_by', 'created_at', 'expires_at', 'used')
    list_filter = ('used', 'created_at')
    search_fields = ('email', 'invited_by__email')
    readonly_fields = ('token', 'created_at', 'used_at')

