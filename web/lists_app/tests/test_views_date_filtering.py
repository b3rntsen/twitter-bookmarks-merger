"""
Tests for date filtering in lists_app views.
"""
import pytest
from django.test import Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import date, timedelta
from twitter.models import TwitterProfile
from lists_app.models import TwitterList, Event


@pytest.mark.django_db
class TestListEventsDateFiltering:
    """Tests for list_events view date filtering."""
    
    def test_list_events_defaults_to_today(self, user, twitter_profile):
        """Test list_events defaults to today's content."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='test_list_123',
            list_name='Test List'
        )
        
        # Create event for today
        today_event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=date.today(),
            headline='Today Event',
            summary='Today summary',
            tweet_count=5,
        )
        
        # Create event for yesterday
        yesterday = date.today() - timedelta(days=1)
        yesterday_event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=yesterday,
            headline='Yesterday Event',
            summary='Yesterday summary',
            tweet_count=3,
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/lists/{twitter_list.id}/events/')
        
        assert response.status_code == 200
        events = list(response.context['events'])
        assert today_event in events
        assert yesterday_event not in events
    
    def test_list_events_filters_by_date_parameter(self, user, twitter_profile):
        """Test list_events filters by date query parameter."""
        twitter_list = TwitterList.objects.create(
            twitter_profile=twitter_profile,
            list_id='test_list_123',
            list_name='Test List'
        )
        
        yesterday = date.today() - timedelta(days=1)
        yesterday_event = Event.objects.create(
            twitter_list=twitter_list,
            event_date=yesterday,
            headline='Yesterday Event',
            summary='Yesterday summary',
            tweet_count=3,
        )
        
        client = Client()
        client.force_login(user)
        
        response = client.get(f'/lists/{twitter_list.id}/events/?date={yesterday}')
        
        assert response.status_code == 200
        events = list(response.context['events'])
        assert yesterday_event in events
        assert response.context['event_date'] == yesterday

