from django.contrib import admin
from .models import TwitterList, ListTweet, Event, EventTweet

admin.site.register(TwitterList)
admin.site.register(ListTweet)
admin.site.register(Event)
admin.site.register(EventTweet)
