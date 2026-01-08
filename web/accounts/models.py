import secrets
from datetime import timedelta

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class UserProfile(models.Model):
    """Extended user profile information."""
    AI_PROVIDER_CHOICES = [
        ('anthropic', 'Anthropic Claude'),
        ('openai', 'OpenAI'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    ai_provider = models.CharField(
        max_length=20,
        choices=AI_PROVIDER_CHOICES,
        default='anthropic',
        help_text="AI provider to use for categorization and summarization"
    )
    is_admin = models.BooleanField(default=False, help_text="Admin users can delete other users")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} Profile"


class Invitation(models.Model):
    """Email invitation for new users."""
    email = models.EmailField(unique=True)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='invitations_sent'
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        status = "used" if self.used else ("expired" if self.is_expired else "pending")
        return f"Invitation for {self.email} ({status})"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.used and not self.is_expired

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']

