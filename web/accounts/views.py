from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import login
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone

from .models import UserProfile, Invitation


@login_required
def auth_check(request):
    """Auth check endpoint for nginx auth_request.

    Returns 200 if authenticated, 401 if not.
    Used by nginx to protect static HTML files.
    """
    return HttpResponse(status=200)


@login_required
def admin_panel(request):
    """User management admin panel. All authenticated users can view."""
    users = User.objects.select_related('profile').order_by('-date_joined')
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)
    pending_invitations = Invitation.objects.filter(used=False).order_by('-created_at')

    return render(request, 'accounts/admin_panel.html', {
        'users': users,
        'is_admin': user_profile.is_admin,
        'pending_invitations': pending_invitations,
    })


@login_required
def invite_user(request):
    """Invite a new user by email."""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()

        # Validate email format
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, 'Please enter a valid email address.')
            return redirect('admin_panel')

        # Check if user already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, f'A user with email {email} already exists.')
            return redirect('admin_panel')

        # Check if invitation already exists
        existing = Invitation.objects.filter(email=email, used=False).first()
        if existing and existing.is_valid:
            messages.warning(request, f'An active invitation for {email} already exists.')
            return redirect('admin_panel')

        # Delete expired/used invitation if exists
        Invitation.objects.filter(email=email).delete()

        # Create new invitation
        invitation = Invitation.objects.create(
            email=email,
            invited_by=request.user,
        )

        messages.success(
            request,
            f'Invitation created for {email}. Share this link: '
            f'{request.build_absolute_uri("/accounts/invite/" + invitation.token + "/")}'
        )
        return redirect('admin_panel')

    return redirect('admin_panel')


def accept_invitation(request, token):
    """Accept invitation and create account with password."""
    invitation = get_object_or_404(Invitation, token=token)

    if invitation.used:
        return render(request, 'accounts/invitation_used.html')

    if invitation.is_expired:
        return render(request, 'accounts/invitation_expired.html')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        errors = []

        # Validate passwords match
        if password != password_confirm:
            errors.append('Passwords do not match.')

        # Validate password strength
        try:
            validate_password(password)
        except ValidationError as e:
            errors.extend(e.messages)

        if errors:
            return render(request, 'accounts/accept_invitation.html', {
                'invitation': invitation,
                'errors': errors,
            })

        # Create user
        user = User.objects.create_user(
            username=invitation.email,
            email=invitation.email,
            password=password,
        )

        # Create profile
        UserProfile.objects.create(user=user)

        # Mark invitation as used
        invitation.used = True
        invitation.used_at = timezone.now()
        invitation.save()

        # Log in the new user
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        messages.success(request, 'Account created successfully! Welcome.')
        return redirect('profile')

    return render(request, 'accounts/accept_invitation.html', {
        'invitation': invitation,
    })


@login_required
def delete_user(request, user_id):
    """Delete a user. Admin only."""
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if not user_profile.is_admin:
        return HttpResponseForbidden("Admin access required")

    if request.method == 'POST':
        user_to_delete = get_object_or_404(User, id=user_id)

        # Can't delete yourself
        if user_to_delete == request.user:
            messages.error(request, "You cannot delete your own account.")
            return redirect('admin_panel')

        email = user_to_delete.email
        user_to_delete.delete()
        messages.success(request, f'User {email} has been deleted.')

    return redirect('admin_panel')


@login_required
def delete_invitation(request, invitation_id):
    """Delete a pending invitation. Admin only."""
    user_profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if not user_profile.is_admin:
        return HttpResponseForbidden("Admin access required")

    if request.method == 'POST':
        invitation = get_object_or_404(Invitation, id=invitation_id)
        email = invitation.email
        invitation.delete()
        messages.success(request, f'Invitation for {email} has been deleted.')

    return redirect('admin_panel')


@login_required
def profile(request):
    """User profile page."""
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Update AI provider preference
        ai_provider = request.POST.get('ai_provider', 'anthropic')
        if ai_provider in ['anthropic', 'openai']:
            profile.ai_provider = ai_provider
            profile.save()
            messages.success(request, f'AI provider updated to {profile.get_ai_provider_display()}.')
            return redirect('profile')
        else:
            messages.error(request, 'Invalid AI provider selected.')
    
    return render(request, 'accounts/profile.html', {'profile': profile})

