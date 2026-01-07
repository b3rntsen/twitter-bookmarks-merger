#!/usr/bin/env python3
"""
Standalone test for cookie format conversion.
Tests the logic without requiring Django setup.
"""

def test_cookie_format_conversion():
    """Test that cookies are properly formatted for Playwright."""
    
    # Simulate stored cookies (from Selenium format) - missing 'path'
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
    
    # Convert cookies (simulating _login_playwright logic)
    playwright_cookies = []
    cookies_list = stored_cookies if isinstance(stored_cookies, list) else [stored_cookies] if stored_cookies else []
    
    for cookie in cookies_list:
        if isinstance(cookie, dict):
            pw_cookie = cookie.copy()
            # Playwright requires either 'url' or both 'domain' and 'path'
            if 'url' not in pw_cookie:
                if 'domain' not in pw_cookie:
                    pw_cookie['domain'] = '.x.com'
                if 'path' not in pw_cookie:
                    pw_cookie['path'] = '/'
            playwright_cookies.append(pw_cookie)
    
    # Verify all cookies have required fields
    errors = []
    for cookie in playwright_cookies:
        if 'name' not in cookie:
            errors.append(f"Cookie missing 'name': {cookie}")
        if 'value' not in cookie:
            errors.append(f"Cookie missing 'value': {cookie}")
        
        # Playwright requires either 'url' OR both 'domain' and 'path'
        has_url = 'url' in cookie
        has_domain_path = 'domain' in cookie and 'path' in cookie
        
        if not (has_url or has_domain_path):
            errors.append(f"Cookie {cookie.get('name')} must have either 'url' or both 'domain' and 'path': {cookie}")
        
        if not has_url:
            if 'domain' not in cookie:
                errors.append(f"Cookie {cookie.get('name')} missing 'domain': {cookie}")
            if 'path' not in cookie:
                errors.append(f"Cookie {cookie.get('name')} missing 'path': {cookie}")
    
    if errors:
        print("TEST FAILED:")
        for error in errors:
            print(f"  - {error}")
        return False
    
    print("TEST PASSED: All cookies have required fields for Playwright")
    print(f"Converted {len(playwright_cookies)} cookies:")
    for cookie in playwright_cookies:
        print(f"  - {cookie.get('name')}: has domain={cookie.get('domain')}, path={cookie.get('path')}")
    return True


if __name__ == '__main__':
    success = test_cookie_format_conversion()
    exit(0 if success else 1)

