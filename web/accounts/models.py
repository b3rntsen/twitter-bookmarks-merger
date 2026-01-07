from django.db import models
from django.contrib.auth.models import User


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} Profile"

