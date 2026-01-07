"""
Template tags for bookmarks app.
"""
from django import template
import os

register = template.Library()


@register.filter
def filename(file_path):
    """
    Extract filename from file path.
    
    Usage: {{ item.file_path|filename }}
    """
    if not file_path:
        return ''
    return os.path.basename(file_path)

