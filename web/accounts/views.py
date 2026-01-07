from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from .models import UserProfile


@login_required
def auth_check(request):
    """Auth check endpoint for nginx auth_request.

    Returns 200 if authenticated, 401 if not.
    Used by nginx to protect static HTML files.
    """
    return HttpResponse(status=200)


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

