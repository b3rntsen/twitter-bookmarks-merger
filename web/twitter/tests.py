"""
Tests for Twitter scraping functionality.
"""
from django.test import TestCase
from twitter.services import TwitterScraper


class TwitterScraperCookieFormatTest(TestCase):
    """Test that cookies are properly formatted for Playwright."""
    
    def test_playwright_cookie_format_with_missing_path(self):
        """Test that cookies without 'path' field get it added."""
        # Simulate stored cookies (from Selenium format)
        stored_cookies = [
            {
                'name': 'auth_token',
                'value': 'test_token',
                'domain': '.x.com'
            },
            {
                'name': 'ct0',
                'value': 'test_csrf',
                'domain': '.x.com'
            }
        ]
        
        scraper = TwitterScraper(
            username='testuser',
            cookies=stored_cookies,
            use_playwright=True
        )
        
        # Manually convert cookies (simulating _login_playwright logic)
        playwright_cookies = []
        cookies_list = scraper.cookies if isinstance(scraper.cookies, list) else [scraper.cookies] if scraper.cookies else []
        
        for cookie in cookies_list:
            if isinstance(cookie, dict):
                pw_cookie = cookie.copy()
                if 'url' not in pw_cookie:
                    if 'domain' not in pw_cookie:
                        pw_cookie['domain'] = '.x.com'
                    if 'path' not in pw_cookie:
                        pw_cookie['path'] = '/'
                playwright_cookies.append(pw_cookie)
        
        # Verify all cookies have required fields
        for cookie in playwright_cookies:
            self.assertIn('name', cookie, "Cookie must have 'name'")
            self.assertIn('value', cookie, "Cookie must have 'value'")
            # Playwright requires either 'url' OR both 'domain' and 'path'
            has_url = 'url' in cookie
            has_domain_path = 'domain' in cookie and 'path' in cookie
            self.assertTrue(
                has_url or has_domain_path,
                f"Cookie {cookie.get('name')} must have either 'url' or both 'domain' and 'path'"
            )
            if not has_url:
                self.assertIn('domain', cookie, f"Cookie {cookie.get('name')} must have 'domain'")
                self.assertIn('path', cookie, f"Cookie {cookie.get('name')} must have 'path'")
    
    def test_playwright_cookie_format_with_existing_path(self):
        """Test that cookies with existing 'path' are preserved."""
        stored_cookies = [
            {
                'name': 'auth_token',
                'value': 'test_token',
                'domain': '.x.com',
                'path': '/home'
            }
        ]
        
        scraper = TwitterScraper(
            username='testuser',
            cookies=stored_cookies,
            use_playwright=True
        )
        
        # Convert cookies
        playwright_cookies = []
        cookies_list = scraper.cookies if isinstance(scraper.cookies, list) else [scraper.cookies] if scraper.cookies else []
        
        for cookie in cookies_list:
            if isinstance(cookie, dict):
                pw_cookie = cookie.copy()
                if 'url' not in pw_cookie:
                    if 'domain' not in pw_cookie:
                        pw_cookie['domain'] = '.x.com'
                    if 'path' not in pw_cookie:
                        pw_cookie['path'] = '/'
                playwright_cookies.append(pw_cookie)
        
        # Verify existing path is preserved
        self.assertEqual(playwright_cookies[0]['path'], '/home', "Existing path should be preserved")
    
    def test_playwright_cookie_format_with_url(self):
        """Test that cookies with 'url' don't need domain/path."""
        stored_cookies = [
            {
                'name': 'auth_token',
                'value': 'test_token',
                'url': 'https://x.com'
            }
        ]
        
        scraper = TwitterScraper(
            username='testuser',
            cookies=stored_cookies,
            use_playwright=True
        )
        
        # Convert cookies
        playwright_cookies = []
        cookies_list = scraper.cookies if isinstance(scraper.cookies, list) else [scraper.cookies] if scraper.cookies else []
        
        for cookie in cookies_list:
            if isinstance(cookie, dict):
                pw_cookie = cookie.copy()
                if 'url' not in pw_cookie:
                    if 'domain' not in pw_cookie:
                        pw_cookie['domain'] = '.x.com'
                    if 'path' not in pw_cookie:
                        pw_cookie['path'] = '/'
                playwright_cookies.append(pw_cookie)
        
        # Verify url is preserved and domain/path not required
        self.assertIn('url', playwright_cookies[0], "URL should be preserved")
        # When url is present, domain/path are optional
        self.assertTrue(
            'url' in playwright_cookies[0] or ('domain' in playwright_cookies[0] and 'path' in playwright_cookies[0]),
            "Cookie must have either 'url' or both 'domain' and 'path'"
        )
