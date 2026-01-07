"""
Custom adapter for django-allauth to handle social account connections.
Allows connecting Google accounts to existing users by email.
"""
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.shortcuts import redirect
from django.http import HttpResponseRedirect

User = get_user_model()


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter that automatically connects social accounts to existing users by email.
    """
    
    def pre_social_login(self, request, sociallogin):
        """
        Called before a social account is connected.
        If a user with the same email exists, connect the social account to that user.
        """
        # If the user is already authenticated, just connect the account
        if request.user.is_authenticated:
            sociallogin.connect(request, request.user)
            return
        
        # Check if a user with this email already exists
        if sociallogin.email_addresses:
            email = sociallogin.email_addresses[0].email
            try:
                user = User.objects.get(email=email)
                # User exists - connect the social account to this user
                if not sociallogin.is_existing:
                    # Connect the social account
                    sociallogin.connect(request, user)
                # Log the user in
                from allauth.account.utils import perform_login
                from allauth.account import app_settings as account_settings
                perform_login(request, user, email_verification=account_settings.EMAIL_VERIFICATION)
                # Redirect to home
                raise ImmediateHttpResponse(
                    HttpResponseRedirect('/')
                )
            except User.DoesNotExist:
                # User doesn't exist - will create new account (default behavior)
                pass
            except User.MultipleObjectsReturned:
                # Multiple users with same email - use the first one
                user = User.objects.filter(email=email).first()
                if user:
                    if not sociallogin.is_existing:
                        sociallogin.connect(request, user)
                    from allauth.account.utils import perform_login
                    from allauth.account import app_settings as account_settings
                    perform_login(request, user, email_verification=account_settings.EMAIL_VERIFICATION)
                    raise ImmediateHttpResponse(
                        HttpResponseRedirect('/')
                    )
    
    def is_open_for_signup(self, request, sociallogin):
        """
        Allow social signups.
        """
        return True
