# Data migration to set nikolaj@dethele.com as admin

from django.db import migrations


def set_initial_admin(apps, schema_editor):
    """Set nikolaj@dethele.com as admin if they exist."""
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')

    try:
        user = User.objects.get(email='nikolaj@dethele.com')
        profile, created = UserProfile.objects.get_or_create(
            user=user,
            defaults={'ai_provider': 'anthropic'}
        )
        profile.is_admin = True
        profile.save()
    except User.DoesNotExist:
        # User hasn't logged in yet - they'll need to be set as admin manually
        # or re-run this migration after they log in
        pass


def reverse_admin(apps, schema_editor):
    """Reverse: remove admin status from nikolaj@dethele.com."""
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')

    try:
        user = User.objects.get(email='nikolaj@dethele.com')
        profile = UserProfile.objects.get(user=user)
        profile.is_admin = False
        profile.save()
    except (User.DoesNotExist, UserProfile.DoesNotExist):
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_userprofile_is_admin_invitation'),
    ]

    operations = [
        migrations.RunPython(set_initial_admin, reverse_admin),
    ]
