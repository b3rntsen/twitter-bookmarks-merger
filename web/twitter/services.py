"""
Twitter scraping service using Selenium/Playwright or Twikit.
"""
import time
import json
import re
from typing import List, Dict, Optional
from django.conf import settings
from decouple import config
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import os
import requests


class TwitterScraper:
    """Scrape Twitter bookmarks using browser automation."""
    
    def __init__(self, username: str, password: Optional[str] = None, cookies: Optional[Dict] = None, use_playwright: bool = False):
        self.username = username
        self.password = password
        self.cookies = cookies
        self.use_playwright = use_playwright
        self.driver = None
        self.context = None  # Playwright browser context
        self.browser = None  # Playwright browser instance
        self.playwright = None  # Playwright process
        self.session_cookies = None
        self.profile_photo_cache = {}  # Cache profile photos by username to avoid repeated fetches
        
    def _init_selenium_driver(self):
        """Initialize Selenium WebDriver with anti-detection measures."""
        chrome_options = Options()
        
        # Try non-headless first if headless fails (macOS security issues)
        use_headless = config('USE_HEADLESS', default='True', cast=lambda v: v.lower() == 'true')
        if use_headless:
            chrome_options.add_argument('--headless=new')  # Use new headless mode
            print("Using headless mode")
        else:
            print("Using visible browser mode (non-headless)")
        
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # Anti-detection measures
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Realistic user agent (macOS)
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36')
        
        # Additional anti-detection
        chrome_options.add_argument('--disable-web-security')
        chrome_options.add_argument('--disable-features=IsolateOrigins,site-per-process')
        chrome_options.add_argument('--disable-site-isolation-trials')
        chrome_options.add_argument('--disable-gpu')
        
        # Set preferences to look more like a real browser
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        
        # Set Chrome binary path for macOS
        chrome_binary_paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ]
        for chrome_path in chrome_binary_paths:
            if os.path.exists(chrome_path):
                chrome_options.binary_location = chrome_path
                print(f"Using Chrome binary: {chrome_path}")
                break
        
        driver_path = config('SELENIUM_DRIVER_PATH', default='/usr/local/bin/chromedriver')
        
        # Resolve symlink to actual path
        if os.path.islink(driver_path):
            driver_path = os.path.realpath(driver_path)
        
        # Verify ChromeDriver exists and is executable
        if not os.path.exists(driver_path):
            raise FileNotFoundError(
                f"ChromeDriver not found at {driver_path}. "
                f"Please install ChromeDriver or update SELENIUM_DRIVER_PATH in .env file. "
                f"Run 'which chromedriver' to find the path."
            )
        
        if not os.access(driver_path, os.X_OK):
            raise PermissionError(
                f"ChromeDriver at {driver_path} is not executable. "
                f"Run 'chmod +x {driver_path}' to fix permissions."
            )
        
        try:
            print(f"Initializing ChromeDriver from: {driver_path}")
            service = Service(driver_path)
            print("Creating Chrome WebDriver instance...")
            # Set service log path to see ChromeDriver errors
            import tempfile
            log_path = tempfile.mktemp(suffix='.log', prefix='chromedriver_')
            service.log_path = log_path
            print(f"ChromeDriver log will be saved to: {log_path}")
            
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            print("ChromeDriver initialized successfully")
            
            # Remove webdriver property to avoid detection
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # Add more realistic browser properties
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                    window.chrome = {runtime: {}};
                '''
            })
            
            # Set realistic viewport
            self.driver.set_window_size(1920, 1080)
        except Exception as e:
            error_msg = str(e) if str(e) else "Unknown error (ChromeDriver may have crashed)"
            print(f"ChromeDriver initialization failed: {error_msg}")
            print(f"ChromeDriver path: {driver_path}")
            print(f"Error type: {type(e).__name__}")
            
            # Try to read ChromeDriver log if it exists
            try:
                if 'log_path' in locals():
                    with open(log_path, 'r') as f:
                        log_content = f.read()
                        if log_content:
                            print(f"ChromeDriver log contents:\n{log_content[-500:]}")  # Last 500 chars
            except:
                pass
            
            # Check if it's a macOS security issue
            if "killed" in error_msg.lower() or "terminated" in error_msg.lower() or not error_msg or "signal" in error_msg.lower():
                raise Exception(
                    f"ChromeDriver was blocked or crashed. This is usually a macOS security issue.\n\n"
                    f"Solutions:\n"
                    f"1. Allow ChromeDriver in System Settings > Privacy & Security > Security\n"
                    f"2. Run: xattr -cr {driver_path}\n"
                    f"3. Try running ChromeDriver manually: {driver_path} --version\n"
                    f"4. If that works, try: USE_HEADLESS=False in .env to use visible browser\n\n"
                    f"See FIX_CHROMEDRIVER_MACOS.md for detailed instructions."
                )
            else:
                raise Exception(
                    f"Failed to initialize ChromeDriver: {error_msg}. "
                    f"Make sure Chrome is installed and ChromeDriver version matches your Chrome version. "
                    f"ChromeDriver path: {driver_path}"
                )
        
    def _init_playwright_driver(self):
        """Initialize Playwright browser (alternative to Selenium)."""
        try:
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
            # Check if we should use headless mode (default to True for production)
            use_headless = config('USE_HEADLESS', default='True', cast=lambda v: v.lower() == 'true')
            self.browser = self.playwright.chromium.launch(headless=use_headless)
            self.context = self.browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            self.driver = self.context.new_page()
            mode = "headless" if use_headless else "non-headless"
            print(f"[PLAYWRIGHT] Initialized browser in {mode} mode (PID: {self.browser.process.pid if hasattr(self.browser, 'process') else 'unknown'})")
        except ImportError:
            raise ImportError("Playwright not installed. Install with: pip install playwright && playwright install chromium")
    
    def login(self):
        """Login to Twitter/X."""
        if self.use_playwright:
            return self._login_playwright()
        else:
            return self._login_selenium()
    
    def _login_selenium(self):
        """Login using Selenium."""
        if not self.driver:
            self._init_selenium_driver()
        
        # If we have cookies, use them
        if self.cookies:
            self.driver.get("https://x.com")
            for cookie in self.cookies:
                try:
                    self.driver.add_cookie(cookie)
                except:
                    pass
            self.driver.refresh()
            time.sleep(2)
            # Handle cookie consent banner if it appears
            self._handle_cookie_consent()
            # Check if we're logged in
            if "home" in self.driver.current_url or self.driver.find_elements(By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"]'):
                return True
        
        # Otherwise, login with credentials
        if not self.password:
            print("No password provided for login")
            return False
        
        # Navigate to login page with realistic delays
        print("Navigating to Twitter login page...")
        self.driver.get("https://x.com/i/flow/login")
        time.sleep(5)  # Longer wait for page to fully load
        
        # Handle cookie consent banner
        self._handle_cookie_consent()
        
        # Random mouse movement simulation (helps avoid detection)
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            actions = ActionChains(self.driver)
            actions.move_by_offset(100, 100).perform()
            time.sleep(1)
        except:
            pass
        
        try:
            # Enter username with human-like typing
            print(f"Looking for username input...")
            username_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[autocomplete="username"]'))
            )
            print(f"Found username input, entering: {self.username}")
            
            # Human-like typing (type character by character with delays)
            username_input.clear()
            time.sleep(0.5)
            for char in self.username:
                username_input.send_keys(char)
                time.sleep(0.1 + (ord(char) % 3) * 0.05)  # Variable delay
            time.sleep(1)
            
            # Click next - try multiple selectors
            print("Looking for Next button...")
            next_button = None
            next_selectors = [
                '//span[text()="Next"]',
                '//span[contains(text(), "Next")]',
                '//button[contains(., "Next")]',
                '//div[@role="button" and contains(., "Next")]',
            ]
            for selector in next_selectors:
                try:
                    next_button = self.driver.find_element(By.XPATH, selector)
                    if next_button:
                        print(f"Found Next button with selector: {selector}")
                        break
                except:
                    continue
            
            if not next_button:
                # Take screenshot for debugging
                screenshot_path = '/tmp/twitter_login_error.png'
                self.driver.save_screenshot(screenshot_path)
                print(f"Could not find Next button. Screenshot saved to {screenshot_path}")
                print(f"Current URL: {self.driver.current_url}")
                print(f"Page source length: {len(self.driver.page_source)}")
                return False
            
            next_button.click()
            print("Clicked Next button")
            time.sleep(3)
            
            # Enter password
            print("Looking for password input...")
            password_input = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[name="password"]'))
            )
            print("Found password input, entering password...")
            password_input.clear()
            time.sleep(0.5)
            # Type password character by character (slower to avoid detection)
            for char in self.password:
                password_input.send_keys(char)
                time.sleep(0.15 + (ord(char) % 3) * 0.05)  # Variable delay
            time.sleep(1.5)
            
            # Click login - try multiple selectors
            print("Looking for Log in button...")
            login_button = None
            login_selectors = [
                '//span[text()="Log in"]',
                '//span[contains(text(), "Log in")]',
                '//button[contains(., "Log in")]',
                '//div[@role="button" and contains(., "Log in")]',
            ]
            for selector in login_selectors:
                try:
                    login_button = self.driver.find_element(By.XPATH, selector)
                    if login_button:
                        print(f"Found Log in button with selector: {selector}")
                        break
                except:
                    continue
            
            if not login_button:
                screenshot_path = '/tmp/twitter_login_error2.png'
                self.driver.save_screenshot(screenshot_path)
                print(f"Could not find Log in button. Screenshot saved to {screenshot_path}")
                print(f"Current URL: {self.driver.current_url}")
                return False
            
            login_button.click()
            print("Clicked Log in button")
            time.sleep(5)
            
            # Check if login was successful
            current_url = self.driver.current_url
            print(f"After login, current URL: {current_url}")
            
            if "home" in current_url or "i/bookmarks" in current_url:
                print("Login successful!")
                # Handle cookie consent banner if it appears after login
                self._handle_cookie_consent()
                # Save cookies for future use
                self.session_cookies = self.driver.get_cookies()
                return True
            elif "login" in current_url or "flow" in current_url:
                print("Still on login page - login may have failed")
                screenshot_path = '/tmp/twitter_login_failed.png'
                self.driver.save_screenshot(screenshot_path)
                print(f"Screenshot saved to {screenshot_path}")
                return False
            else:
                print(f"Unknown state after login. URL: {current_url}")
                return True  # Assume success if we're not on login page
            
        except TimeoutException as e:
            print(f"Login timeout: {e}")
            screenshot_path = '/tmp/twitter_login_timeout.png'
            try:
                self.driver.save_screenshot(screenshot_path)
                print(f"Screenshot saved to {screenshot_path}")
            except:
                pass
            return False
        except NoSuchElementException as e:
            print(f"Element not found during login: {e}")
            screenshot_path = '/tmp/twitter_login_element_not_found.png'
            try:
                self.driver.save_screenshot(screenshot_path)
                print(f"Screenshot saved to {screenshot_path}")
                print(f"Current URL: {self.driver.current_url}")
            except:
                pass
            return False
        except Exception as e:
            print(f"Login failed with error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def _login_playwright(self):
        """Login using Playwright."""
        if not self.driver:
            self._init_playwright_driver()
        
        # Similar logic for Playwright
        if self.cookies:
            self.driver.goto("https://x.com")
            try:
                # Convert cookies to Playwright format (requires url or domain/path)
                playwright_cookies = []
                cookies_list = self.cookies if isinstance(self.cookies, list) else [self.cookies] if self.cookies else []
                
                print(f"[PLAYWRIGHT] Converting {len(cookies_list)} cookies for Playwright format")
                
                for cookie in cookies_list:
                    if isinstance(cookie, dict):
                        # Ensure cookie has required fields for Playwright
                        pw_cookie = cookie.copy()
                        # Playwright requires either 'url' OR both 'domain' and 'path'
                        if 'url' not in pw_cookie:
                            # Ensure domain is set (should already be there from stored cookies)
                            if 'domain' not in pw_cookie:
                                pw_cookie['domain'] = '.x.com'  # Default to Twitter domain
                                print(f"[PLAYWRIGHT] Added missing 'domain' to cookie {pw_cookie.get('name', 'unknown')}")
                            # Ensure path is set (required by Playwright)
                            if 'path' not in pw_cookie:
                                pw_cookie['path'] = '/'
                                print(f"[PLAYWRIGHT] Added missing 'path' to cookie {pw_cookie.get('name', 'unknown')}")
                        
                        # Validate cookie has required fields before adding
                        has_url = 'url' in pw_cookie
                        has_domain_path = 'domain' in pw_cookie and 'path' in pw_cookie
                        if not (has_url or has_domain_path):
                            raise ValueError(
                                f"Cookie {pw_cookie.get('name', 'unknown')} missing required fields. "
                                f"Must have either 'url' or both 'domain' and 'path'. "
                                f"Cookie keys: {list(pw_cookie.keys())}"
                            )
                        
                        playwright_cookies.append(pw_cookie)
                    else:
                        print(f"[PLAYWRIGHT] WARNING: Skipping non-dict cookie: {type(cookie)}")
                
                if playwright_cookies:
                    print(f"[PLAYWRIGHT] Adding {len(playwright_cookies)} cookies to browser context")
                    # Validate all cookies one more time before passing to Playwright
                    for cookie in playwright_cookies:
                        if 'url' not in cookie and ('domain' not in cookie or 'path' not in cookie):
                            raise ValueError(f"Invalid cookie format: {cookie}")
                    
                    self.driver.context.add_cookies(playwright_cookies)
                    self.driver.reload()
                    time.sleep(3)  # Give more time for page to load
                    
                    # Check multiple indicators of being logged in
                    current_url = self.driver.url
                    is_home = "home" in current_url or "twitter.com/home" in current_url
                    
                    # Try to check for logged-in elements
                    try:
                        # Look for account switcher or navigation that indicates logged in
                        logged_in_indicators = [
                            self.driver.locator('[data-testid="SideNav_AccountSwitcher_Button"]').count() > 0,
                            self.driver.locator('a[href*="/compose/tweet"]').count() > 0,
                            self.driver.locator('nav[role="navigation"]').count() > 0,
                        ]
                        has_logged_in_elements = any(logged_in_indicators)
                    except:
                        has_logged_in_elements = False
                    
                    # Also try navigating to bookmarks page to verify login
                    try:
                        self.driver.goto("https://x.com/i/bookmarks")
                        time.sleep(2)
                        bookmarks_url = self.driver.url
                        # If we can access bookmarks page (not redirected to login), we're logged in
                        can_access_bookmarks = "bookmarks" in bookmarks_url and "login" not in bookmarks_url
                    except:
                        can_access_bookmarks = False
                    
                    if is_home or has_logged_in_elements or can_access_bookmarks:
                        print(f"[PLAYWRIGHT] Cookie login successful (URL: {current_url}, indicators: home={is_home}, elements={has_logged_in_elements}, bookmarks={can_access_bookmarks})")
                        return True
                    else:
                        print(f"[PLAYWRIGHT] Cookie login failed - current URL: {current_url}, indicators: home={is_home}, elements={has_logged_in_elements}, bookmarks={can_access_bookmarks}")
                else:
                    print("[PLAYWRIGHT] No valid cookies to add")
            except Exception as e:
                import traceback
                print(f"[PLAYWRIGHT] Error adding cookies: {e}")
                print(f"[PLAYWRIGHT] Traceback: {traceback.format_exc()}")
                if playwright_cookies:
                    print(f"[PLAYWRIGHT] First cookie format: {playwright_cookies[0] if playwright_cookies else 'None'}")
                # Continue to password login if cookie login fails
        
        if not self.password:
            return False
        
        self.driver.goto("https://x.com/i/flow/login")
        time.sleep(3)
        
        # Enter credentials (similar to Selenium)
        self.driver.fill('input[autocomplete="username"]', self.username)
        self.driver.click('text=Next')
        time.sleep(2)
        self.driver.fill('input[name="password"]', self.password)
        self.driver.click('text=Log in')
        time.sleep(5)
        
        return True
    
    def _expand_tco_link(self, tco_url: str) -> Optional[str]:
        """Follow t.co redirect to get final destination URL."""
        try:
            # Follow redirect but stop at first redirect to get final destination
            response = requests.head(
                tco_url,
                allow_redirects=True,
                timeout=5,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                }
            )
            final_url = response.url
            # If it's still t.co, try GET request
            if 't.co' in final_url:
                response = requests.get(
                    tco_url,
                    allow_redirects=True,
                    timeout=5,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                    }
                )
                final_url = response.url
            return final_url if final_url != tco_url else None
        except Exception as e:
            print(f"Error expanding t.co link {tco_url}: {e}")
            return None
    
    def _handle_cookie_consent(self):
        """Handle Twitter's cookie consent banner by refusing non-essential cookies."""
        try:
            print("Checking for cookie consent banner...")
            # Wait a bit for the banner to appear
            time.sleep(2)
            
            # Try multiple selectors for the "Refuse non-essential cookies" button
            refuse_selectors = [
                '//span[contains(text(), "Refuse non-essential cookies")]',
                '//button[contains(., "Refuse non-essential cookies")]',
                '//div[@role="button" and contains(., "Refuse non-essential cookies")]',
                '//span[contains(text(), "Refuse")]',
                '//button[contains(., "Refuse")]',
                # Also try case-insensitive variations
                '//span[contains(translate(text(), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "refuse non-essential")]',
                '//button[contains(translate(., "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "refuse non-essential")]',
            ]
            
            refuse_button = None
            for selector in refuse_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for element in elements:
                        # Make sure it's visible and clickable
                        if element.is_displayed() and element.is_enabled():
                            refuse_button = element
                            print(f"Found refuse cookies button with selector: {selector}")
                            break
                    if refuse_button:
                        break
                except:
                    continue
            
            if refuse_button:
                try:
                    # Scroll to button if needed
                    self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", refuse_button)
                    time.sleep(0.5)
                    refuse_button.click()
                    print("Clicked 'Refuse non-essential cookies' button")
                    time.sleep(2)  # Wait for banner to disappear
                    return True
                except Exception as e:
                    print(f"Error clicking refuse cookies button: {e}")
                    # Try JavaScript click as fallback
                    try:
                        self.driver.execute_script("arguments[0].click();", refuse_button)
                        print("Clicked 'Refuse non-essential cookies' button (via JavaScript)")
                        time.sleep(2)
                        return True
                    except:
                        pass
            
            # If refuse button not found, check if banner exists at all
            cookie_banner_selectors = [
                '//div[contains(text(), "cookies")]',
                '//div[contains(text(), "Cookies")]',
                '//div[contains(@class, "cookie")]',
            ]
            
            banner_found = False
            for selector in cookie_banner_selectors:
                try:
                    if self.driver.find_elements(By.XPATH, selector):
                        banner_found = True
                        break
                except:
                    pass
            
            if not banner_found:
                print("No cookie consent banner found (may have already been handled)")
            else:
                print("Cookie banner found but refuse button not located")
            
            return False
            
        except Exception as e:
            print(f"Error handling cookie consent: {e}")
            return False
    
    def _execute_js(self, script: str):
        """Execute JavaScript - works with both Selenium and Playwright."""
        if self.use_playwright:
            # Playwright evaluate() expects an expression, not a statement
            # Remove 'return' if present - evaluate() automatically returns the expression value
            script = script.strip()
            if script.startswith('return '):
                script = script[7:].strip()
            # Playwright evaluate returns the result directly
            return self.driver.evaluate(script)
        else:
            # Selenium execute_script can handle 'return' statements
            return self.driver.execute_script(script)
    
    def _get_current_url(self) -> str:
        """Get current URL - works with both Selenium and Playwright."""
        if self.use_playwright:
            return self.driver.url
        else:
            return self.driver.current_url
    
    def _find_tweet_elements(self):
        """Find all tweet article elements - works with both Selenium and Playwright."""
        if self.use_playwright:
            return self.driver.locator('article[data-testid="tweet"]').all()
        else:
            return self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
    
    def get_bookmarks(self, max_bookmarks: int = 1000) -> List[Dict]:
        """Scrape bookmarks from Twitter with pagination - supports both Selenium and Playwright."""
        if not self.driver:
            if not self.login():
                raise Exception("Failed to login to Twitter")
        
        bookmarks = []
        seen_tweet_ids = set()  # Track seen tweets by ID to avoid duplicates
        
        print("Navigating to bookmarks page...")
        # Use appropriate method based on browser type
        if self.use_playwright:
            # Use "load" instead of "networkidle" - Twitter/X has continuous network activity
            # "load" waits for the load event, which is sufficient for page navigation
            # Increase timeout to 60 seconds to handle slow connections
            self.driver.goto("https://x.com/i/bookmarks", wait_until="load", timeout=60000)
        else:
            self.driver.get("https://x.com/i/bookmarks")
        time.sleep(8)  # Increased wait time for page to fully load
        
        # Handle cookie consent banner if it appears
        self._handle_cookie_consent()
        
        # Wait for initial content to load - retry multiple times
        tweets_found = False
        for attempt in range(5):  # Try up to 5 times
            try:
                if self.use_playwright:
                    self.driver.wait_for_selector('article[data-testid="tweet"]', timeout=15000)
                    # Verify we actually have tweets
                    tweet_elements = self._find_tweet_elements()
                    if len(tweet_elements) > 0:
                        print(f"Bookmarks page loaded - found {len(tweet_elements)} tweets")
                        tweets_found = True
                        break
                    else:
                        print(f"Wait attempt {attempt + 1}/5: Selector found but no tweets yet, waiting...")
                        time.sleep(3)
                else:
                    WebDriverWait(self.driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
                    )
                    tweet_elements = self._find_tweet_elements()
                    if len(tweet_elements) > 0:
                        print(f"Bookmarks page loaded - found {len(tweet_elements)} tweets")
                        tweets_found = True
                        break
                    else:
                        print(f"Wait attempt {attempt + 1}/5: Selector found but no tweets yet, waiting...")
                        time.sleep(3)
            except (TimeoutException, Exception) as e:
                print(f"Wait attempt {attempt + 1}/5: No tweets found yet, waiting... ({e})")
                time.sleep(3)
        
        if not tweets_found:
            print("Warning: No tweets found after multiple attempts, continuing anyway...")
        
        # Scroll and collect bookmarks
        last_height = self._execute_js("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scrolls = 100  # Increased significantly to handle many bookmarks
        no_new_bookmarks_count = 0
        max_no_new_bookmarks = 5  # Stop if no new bookmarks found after 5 scrolls
        
        max_limit = max_bookmarks if max_bookmarks > 0 else float('inf')
        print(f"Starting to collect bookmarks (max: {'all' if max_bookmarks == 0 else max_bookmarks})...")
        
        while len(bookmarks) < max_limit and scroll_attempts < max_scrolls:
            # Find all tweet articles
            tweet_elements = self._find_tweet_elements()
            print(f"Found {len(tweet_elements)} tweet elements on page, currently have {len(bookmarks)} unique bookmarks")
            
            new_bookmarks_this_scroll = 0
            for element in tweet_elements:
                try:
                    # Wrap Playwright locators to work with _extract_tweet_data
                    if self.use_playwright:
                        from twitter.services_playwright_helpers import PlaywrightElementWrapper
                        wrapped_element = PlaywrightElementWrapper(element)
                    else:
                        wrapped_element = element
                    
                    tweet_data = self._extract_tweet_data(wrapped_element)
                    if tweet_data and tweet_data.get('tweet_id'):
                        tweet_id = tweet_data['tweet_id']
                        if tweet_id not in seen_tweet_ids:
                            seen_tweet_ids.add(tweet_id)
                            bookmarks.append(tweet_data)
                            new_bookmarks_this_scroll += 1
                except Exception as e:
                    print(f"Error extracting tweet: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            # Check if we got new bookmarks
            if new_bookmarks_this_scroll == 0:
                no_new_bookmarks_count += 1
                print(f"No new bookmarks this scroll ({no_new_bookmarks_count}/{max_no_new_bookmarks})")
                if no_new_bookmarks_count >= max_no_new_bookmarks:
                    print(f"No new bookmarks found after {max_no_new_bookmarks} scrolls. Reached end of bookmarks.")
                    break
            else:
                no_new_bookmarks_count = 0
                print(f"Added {new_bookmarks_this_scroll} new bookmarks (total: {len(bookmarks)})")
            
            # Scroll down smoothly - multiple scrolls to trigger lazy loading
            self._execute_js("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)  # Increased wait time for new content to load
            
            # Additional scroll to trigger more content
            self._execute_js("window.scrollBy(0, 1000);")
            time.sleep(2)  # Increased wait time
            
            # Check if we've reached the bottom
            new_height = self._execute_js("return document.body.scrollHeight")
            scroll_position = self._execute_js("return window.pageYOffset + window.innerHeight")
            
            if new_height == last_height and scroll_position >= new_height - 100:
                # We're at the bottom and page height hasn't changed
                scroll_attempts += 1
                print(f"At bottom of page (scroll attempt {scroll_attempts}/{max_scrolls})")
            else:
                scroll_attempts = 0
                print(f"Page loaded more content (height: {new_height}, scroll: {scroll_position})")
            
            last_height = new_height
            
            # Progress update every 10 bookmarks
            if len(bookmarks) > 0 and len(bookmarks) % 10 == 0:
                print(f"Progress: {len(bookmarks)} bookmarks collected so far...")
        
        print(f"Finished collecting {len(bookmarks)} unique bookmarks")
        
        # Post-processing: Fetch full text for tweets with "Show more" links
        # Collect tweets needing full text during extraction
        tweets_needing_full_text = []
        for bookmark in bookmarks:
            if bookmark.get('needs_full_text', False) and bookmark.get('tweet_url'):
                tweets_needing_full_text.append({
                    'tweet_data': bookmark,
                    'tweet_url': bookmark['tweet_url'],
                    'tweet_id': bookmark.get('tweet_id', 'unknown')
                })
        
        # Batch navigate to detail pages and fetch full text
        if tweets_needing_full_text:
            try:
                print(f"Found {len(tweets_needing_full_text)} bookmarks with 'Show more' links, fetching full text...")
                self._fetch_full_text_batch(tweets_needing_full_text)
            except Exception as e:
                print(f"Error during full text batch fetching: {e}")
                import traceback
                traceback.print_exc()
                # Continue - truncated text will be used as fallback
        
        # Post-processing: Fetch missing profile photos for usernames that don't have them
        # This is done after extraction to avoid stale element references
        print("Fetching missing profile photos...")
        usernames_needing_photos = set()
        for bookmark in bookmarks:
            username = bookmark.get('author_username', '')
            profile_photo = bookmark.get('author_profile_image_url', '')
            if username and not profile_photo and username not in self.profile_photo_cache:
                usernames_needing_photos.add(username)
        
        # Fetch profile photos in batch (one navigation per username)
        for username in usernames_needing_photos:
            try:
                profile_photo_url = self._fetch_profile_photo_from_page(username)
                if profile_photo_url:
                    self.profile_photo_cache[username] = profile_photo_url
                    # Update all bookmarks for this username
                    for bookmark in bookmarks:
                        if bookmark.get('author_username') == username and not bookmark.get('author_profile_image_url'):
                            bookmark['author_profile_image_url'] = profile_photo_url
            except Exception as e:
                print(f"Warning: Could not fetch profile photo for {username}: {e}")
                continue
        
        # Return to bookmarks page in case we navigated away
        try:
            current_url = self._get_current_url()
            if self.driver and 'bookmarks' not in current_url.lower():
                if self.use_playwright:
                    self.driver.goto("https://x.com/i/bookmarks")
                else:
                    self.driver.get("https://x.com/i/bookmarks")
                time.sleep(2)
        except:
            pass
        
        return bookmarks[:max_bookmarks] if max_bookmarks > 0 else bookmarks
    
    def _extract_tweet_data(self, element) -> Optional[Dict]:
        """Extract data from a tweet element - works with both Selenium and Playwright (via wrapper)."""
        try:
            # Extract tweet ID from URL
            # element is either a Selenium WebElement or a PlaywrightElementWrapper
            tweet_link = element.find_element(By.CSS_SELECTOR, 'a[href*="/status/"]')
            tweet_url = tweet_link.get_attribute('href')
            tweet_id = re.search(r'/status/(\d+)', tweet_url)
            if not tweet_id:
                return None
            tweet_id = tweet_id.group(1)
            
            # Extract author info - get the username from the author link
            author_link = element.find_element(By.CSS_SELECTOR, 'a[href^="/"][href*="/"]')
            author_href = author_link.get_attribute('href')
            
            # Extract username from href - handle both relative and absolute URLs
            # Examples: "/AnthropicAI" -> "AnthropicAI"
            #           "https://x.com/AnthropicAI" -> "AnthropicAI"
            #           "http://x.com/AnthropicAI" -> "AnthropicAI"
            if author_href:
                # Remove protocol and domain if present
                author_href = author_href.replace('https://', '').replace('http://', '')
                author_href = author_href.replace('x.com/', '').replace('twitter.com/', '')
                # Remove leading/trailing slashes and get first part
                author_username = author_href.strip('/').split('/')[0] if author_href else ''
                # Remove @ if present
                if author_username.startswith('@'):
                    author_username = author_username[1:]
            else:
                author_username = ''
            
            # Extract display name (the visible name, not the handle) - this is the bold name
            author_display_name = author_username  # Default to username
            try:
                # The display name is usually the first span in User-Name that's not the handle
                user_name_container = element.find_element(By.CSS_SELECTOR, '[data-testid="User-Name"]')
                # Get all spans and find the one that's the display name (not starting with @)
                name_spans = user_name_container.find_elements(By.CSS_SELECTOR, 'span')
                for span in name_spans:
                    text = span.text.strip()
                    # Display name is the one that doesn't start with @ and is not empty
                    if text and not text.startswith('@') and len(text) > 0 and text != author_username:
                        author_display_name = text
                        break
            except:
                try:
                    # Fallback: look for the first non-handle text near the author link
                    parent = author_link.find_element(By.XPATH, './ancestor::div[1]')
                    spans = parent.find_elements(By.CSS_SELECTOR, 'span')
                    for span in spans:
                        text = span.text.strip()
                        if text and not text.startswith('@') and text != author_username and len(text) > 1:
                            author_display_name = text
                            break
                except:
                    pass
            
            # Extract profile picture - this is the SMALL circular avatar, NOT post media
            # Profile pictures are in the UserAvatar container, usually small and circular
            # They appear in the tweet HEADER, before the tweet content/media
            # CRITICAL: Must exclude images from the tweet content/media area
            # Note: Profile photos are also available at https://x.com/{username}/photo
            # but we extract from DOM to get the actual image URL
            author_profile_image_url = ''
            
            try:
                # Strategy 1: Find UserAvatar container - most reliable and safest
                # The avatar is always in a container with data-testid starting with "UserAvatar"
                avatar_containers = element.find_elements(By.CSS_SELECTOR, 'div[data-testid^="UserAvatar"]')
                for container in avatar_containers:
                    try:
                        # Find img inside the avatar container
                        avatar_img = container.find_element(By.CSS_SELECTOR, 'img')
                        src = avatar_img.get_attribute('src') or avatar_img.get_attribute('data-src') or ''
                        if src and 'pbs.twimg.com' in src:
                            # Profile images ALWAYS have 'profile_images' in the URL
                            # This is the definitive identifier - if it has profile_images, it's a profile pic
                            if 'profile_images' in src:
                                base_url = src.split('?')[0]
                                # Remove size suffixes (_normal, _bigger, etc.) before adding ?name=orig
                                size_suffixes = ['_normal', '_bigger', '_mini', '_200x200', '_400x400', '_original']
                                for suffix in size_suffixes:
                                    if suffix in base_url:
                                        # Remove suffix but keep file extension
                                        base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                        break
                                author_profile_image_url = base_url + '?name=orig'
                                break
                    except:
                        continue
                
                # Strategy 2: If UserAvatar container not found, look in header area only
                # Find images near the author name, but ONLY in the header, NOT in content/media
                if not author_profile_image_url:
                    try:
                        # Find the tweet header section (where author info is displayed)
                        # The header contains: avatar, author name, handle, timestamp
                        # It does NOT contain tweet content or media
                        tweet_header = element.find_element(By.CSS_SELECTOR, 'div[data-testid="User-Name"]')
                        
                        # Navigate up to find the header container that holds avatar + name
                        # The header is typically structured as: header > avatar + name section
                        # We want to find images in the header area, before any content
                        header_parent = tweet_header.find_element(By.XPATH, './ancestor::div[1]')
                        
                        # Look for images in the header parent, but be very selective
                        header_imgs = header_parent.find_elements(By.CSS_SELECTOR, 'img')
                        
                        for img in header_imgs:
                            src = img.get_attribute('src') or img.get_attribute('data-src') or ''
                            if not src or 'pbs.twimg.com' not in src:
                                continue
                            
                            # CRITICAL: Profile images MUST have 'profile_images' in the URL path
                            # This is the only reliable way to distinguish from post media
                            if 'profile_images' not in src:
                                continue
                            
                            # EXCLUDE post media images - they have these patterns:
                            if any(exclude in src.lower() for exclude in ['/media/', '/ext_tw_video_thumb', '/video_thumb', 'media_', 'video_']):
                                continue
                            
                            # Verify it's small (avatar size, not post media)
                            # Profile avatars are typically 40-50px, post media is 200px+
                            try:
                                img_size = img.size
                                if img_size['width'] <= 60 and img_size['height'] <= 60:
                                    base_url = src.split('?')[0]
                                    # Remove size suffixes before adding ?name=orig
                                    size_suffixes = ['_normal', '_bigger', '_mini', '_200x200', '_400x400']
                                    for suffix in size_suffixes:
                                        if suffix in base_url:
                                            base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                            break
                                    author_profile_image_url = base_url + '?name=orig'
                                    break
                            except:
                                # If we can't check size, but it has profile_images and no media indicators,
                                # it's likely a profile picture
                                base_url = src.split('?')[0]
                                # Remove size suffixes
                                size_suffixes = ['_normal', '_bigger', '_mini', '_200x200', '_400x400']
                                for suffix in size_suffixes:
                                    if suffix in base_url:
                                        base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                        break
                                author_profile_image_url = base_url + '?name=orig'
                                break
                                
                    except:
                        pass
                
                        # Strategy 3: Last resort - scan all images but be VERY strict
                        # Only accept if: has profile_images, is small, and NOT in media section
                        if not author_profile_image_url:
                            try:
                                # Try to identify the content/media section to exclude it
                                content_section = None
                                try:
                                    # Tweet content/media is usually in a section after the header
                                    # Try multiple selectors for tweet text (Twitter changed structure)
                                    tweet_text = None
                                    text_selectors = [
                                        '[data-testid="tweetText"]',
                                        'div[data-testid="tweetText"]',
                                        '[role="text"]',
                                        'div[dir="auto"]',
                                    ]
                                    for selector in text_selectors:
                                        try:
                                            tweet_text = element.find_element(By.CSS_SELECTOR, selector)
                                            break
                                        except:
                                            continue
                                    
                                    if tweet_text:
                                        content_section = tweet_text.find_element(By.XPATH, './ancestor::div[contains(@data-testid, "tweet") or @role="article"][1]')
                                except:
                                    pass
                                
                                # Get all images in the tweet
                                all_imgs = element.find_elements(By.CSS_SELECTOR, 'img')
                                
                                for img in all_imgs:
                                    src = img.get_attribute('src') or img.get_attribute('data-src') or ''
                                    if not src or 'pbs.twimg.com' not in src:
                                        continue
                                    
                                    # MUST have 'profile_images' in URL - this is non-negotiable
                                    if 'profile_images' not in src:
                                        continue
                                    
                                    # EXCLUDE any images that look like post media
                                    if any(exclude in src.lower() for exclude in ['/media/', '/ext_tw_video_thumb', '/video_thumb', 'media_', 'video_']):
                                        continue
                                    
                                    # If we identified content section, skip images in it
                                    if content_section:
                                        try:
                                            if img.find_element(By.XPATH, './ancestor::div[1]') == content_section.find_element(By.XPATH, '.'):
                                                continue
                                        except:
                                            pass
                                    
                                    # Check size - profile avatars are small (60px or less)
                                    try:
                                        img_size = img.size
                                        if img_size['width'] <= 60 and img_size['height'] <= 60:
                                            base_url = src.split('?')[0]
                                            # Remove size suffixes before adding ?name=orig
                                            size_suffixes = ['_normal', '_bigger', '_mini', '_200x200', '_400x400']
                                            for suffix in size_suffixes:
                                                if suffix in base_url:
                                                    base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                                    break
                                            author_profile_image_url = base_url + '?name=orig'
                                            break
                                    except:
                                        # Last resort: if it has profile_images and passes all other checks
                                        # but we can't verify size, skip it to be safe
                                        pass
                            except:
                                pass
                
                # Strategy 4: Fallback - fetch profile photo URL from profile photo page
                # If DOM extraction failed, navigate to https://x.com/{username}/photo
                # and extract the actual profile image URL
                if not author_profile_image_url and author_username:
                    try:
                        author_profile_image_url = self._fetch_profile_photo_from_page(author_username)
                    except Exception as e:
                        # If this fails, we'll just leave it empty and show placeholder
                        print(f"Warning: Could not fetch profile photo for {author_username}: {e}")
                        pass
                        
            except Exception as e:
                # Log but don't fail - profile picture is optional
                # If we can't find it, that's okay - we'll show a placeholder
                pass
            
            # Final fallback: Only fetch from profile photo page if DOM extraction completely failed
            # AND we haven't already cached a profile photo for this username
            # We do NOT fetch during extraction to avoid stale element references
            # Profile photos will be fetched in batch after all tweets are extracted
            if author_username and not author_profile_image_url:
                # Check cache first
                if author_username in self.profile_photo_cache:
                    author_profile_image_url = self.profile_photo_cache[author_username]
                # Don't fetch during extraction - it causes stale element references
                # We'll handle missing profile photos in a post-processing step
            
            # Extract HTML content of the tweet
            html_content = element.get_attribute('outerHTML')
            
            # Extract text and links - Twitter/X changed their structure
            # Try multiple selectors as fallbacks
            text_content = ""
            text_selectors = [
                '[data-testid="tweetText"]',  # Old selector (may still work in some cases)
                'div[data-testid="tweetText"]',  # Explicit div
                'span[data-testid="tweetText"]',  # May be a span
                'div[lang]',  # Tweet text often has lang attribute
                '[role="text"]',  # Alternative role-based selector
                'div[dir="auto"]',  # Text content often has dir="auto"
            ]
            
            for selector in text_selectors:
                try:
                    text_element = element.find_element(By.CSS_SELECTOR, selector)
                    text_content = text_element.text if text_element else ""
                    if text_content and len(text_content.strip()) > 0:
                        break
                except:
                    continue
            
            # If all selectors fail, try to extract text from the article element itself
            # but exclude author info, timestamps, and engagement buttons
            if not text_content or len(text_content.strip()) == 0:
                try:
                    # Get all text from the element, then try to clean it up
                    all_text = element.text
                    # Try to find the main content area by excluding known patterns
                    # Look for divs that contain text but aren't in header/engagement areas
                    content_divs = element.find_elements(By.CSS_SELECTOR, 'div[dir="auto"]')
                    for div in content_divs:
                        div_text = div.text.strip()
                        # Skip if it's too short (likely metadata) or contains engagement text
                        if len(div_text) > 10 and 'like' not in div_text.lower() and 'reply' not in div_text.lower():
                            text_content = div_text
                            break
                except:
                    pass
            
            # Final fallback: extract from article text but filter out common non-content text
            if not text_content or len(text_content.strip()) == 0:
                try:
                    all_text = element.text
                    # Split by newlines and find the longest text block (likely the tweet content)
                    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
                    # Filter out lines that look like metadata (short, contain @, contain numbers only, etc.)
                    content_lines = []
                    for line in lines:
                        # Skip if it's clearly metadata
                        if (len(line) < 3 or 
                            line.startswith('@') and len(line.split()) == 1 or
                            line.replace('.', '').replace(',', '').isdigit() or
                            '·' in line and len(line) < 20 or
                            'Replying to' in line or
                            'Show this thread' in line):
                            continue
                        content_lines.append(line)
                    
                    if content_lines:
                        # Join the content lines, prioritizing longer ones
                        text_content = ' '.join(sorted(content_lines, key=len, reverse=True)[:3])
                except:
                    pass
            
            # Extract links from tweet (including t.co links)
            links = []
            try:
                link_elements = element.find_elements(By.CSS_SELECTOR, 'a[href*="t.co"]')
                for link_elem in link_elements:
                    tco_url = link_elem.get_attribute('href')
                    if tco_url and 't.co' in tco_url:
                        # Follow redirect to get final URL
                        expanded_url = self._expand_tco_link(tco_url)
                        if expanded_url:
                            links.append({
                                'tco_url': tco_url,
                                'expanded_url': expanded_url,
                                'text': link_elem.text or expanded_url
                            })
            except Exception as e:
                print(f"Error extracting links: {e}")
            
            # Extract timestamp
            time_element = element.find_element(By.CSS_SELECTOR, 'time')
            timestamp = time_element.get_attribute('datetime') if time_element else None
            
            # Extract engagement metrics
            like_count = self._extract_metric(element, 'like')
            retweet_count = self._extract_metric(element, 'retweet')
            reply_count = self._extract_metric(element, 'reply')
            
            # Extract media URLs - check both src and data-src (for lazy loading)
            media_urls = []
            
            # First, extract video URLs separately for better handling
            video_urls = self._extract_video_urls(element)
            media_urls.extend(video_urls)
            
            # Then extract image URLs
            # Try multiple selectors for media
            media_selectors = [
                'img[src*="pbs.twimg.com"]',
                'img[data-src*="pbs.twimg.com"]',
                'img[src*="video.twimg.com"]',
            ]
            
            for selector in media_selectors:
                media_elements = element.find_elements(By.CSS_SELECTOR, selector)
                for media in media_elements:
                    # Try src first, then data-src
                    src = media.get_attribute('src') or media.get_attribute('data-src')
                    if src and ('pbs.twimg.com' in src or 'video.twimg.com' in src):
                        # Skip if this is a video thumbnail (already handled by video extraction)
                        if 'video.twimg.com' in src and ('thumb' in src.lower() or 'preview' in src.lower()):
                            continue
                        
                        # Clean URL - get base URL without query params
                        base_url = src.split('?')[0]
                        
                        # For profile images, remove size suffixes and add ?name=orig
                        if 'profile_images' in base_url:
                            # Remove size suffixes: _normal, _bigger, _mini, _200x200, etc.
                            size_suffixes = ['_normal', '_bigger', '_mini', '_200x200', '_400x400', '_original']
                            for suffix in size_suffixes:
                                if suffix in base_url:
                                    # Remove suffix but keep file extension
                                    base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                    break
                            # Add ?name=orig for full resolution profile images
                            src = base_url + '?name=orig'
                        # For media images (not profile), try to get original format
                        elif '/media/' in base_url:
                            # Media images: try ?name=orig, but if it has format params, keep them
                            if '?format=' in src or '?name=' in src:
                                # Already has format/name params, use as-is
                                src = src
                            else:
                                # Try to get original format
                                src = base_url + '?name=orig'
                        # For card images, don't add ?name=orig - they might not support it
                        elif '/card_img/' in base_url:
                            # Card images: use URL as-is, don't modify
                            src = src
                        # For other types, use URL as-is
                        else:
                            # Use the original URL without modification
                            src = src
                        
                        media_urls.append(src)
            
            # Remove duplicates while preserving order
            seen = set()
            unique_media_urls = []
            for url in media_urls:
                # Use base URL without query params as key
                base_url = url.split('?')[0]
                if base_url not in seen:
                    seen.add(base_url)
                    unique_media_urls.append(url)
            
            media_urls = unique_media_urls
            
            # Check if it's a reply
            is_reply = bool(element.find_elements(By.CSS_SELECTOR, '[data-testid="reply"]'))
            
            # Detect "Show more" link if present
            needs_full_text, full_text_url = self._detect_show_more_link(element)
            
            return {
                'tweet_id': tweet_id,
                'author_username': author_username,
                'author_display_name': author_display_name,
                'author_profile_image_url': author_profile_image_url,
                'text_content': text_content,
                'created_at': timestamp,
                'like_count': like_count,
                'retweet_count': retweet_count,
                'reply_count': reply_count,
                'media_urls': media_urls,
                'is_reply': is_reply,
                'url': tweet_url,
                'links': links,  # Store expanded links
                'html_content': html_content,  # Store original HTML
                'needs_full_text': needs_full_text,  # NEW: Flag indicating "Show more" detected
                'tweet_url': full_text_url if needs_full_text else tweet_url,  # NEW: URL for detail page navigation
            }
        except Exception as e:
            print(f"Error extracting tweet data: {e}")
            return None
    
    def _extract_metric(self, element, metric_type: str) -> int:
        """Extract engagement metric (likes, retweets, replies)."""
        try:
            selectors = {
                'like': '[data-testid="like"]',
                'retweet': '[data-testid="retweet"]',
                'reply': '[data-testid="reply"]',
            }
            metric_element = element.find_element(By.CSS_SELECTOR, selectors.get(metric_type, ''))
            metric_text = metric_element.text if metric_element else "0"
            # Extract number from text like "1.2K" or "123"
            numbers = re.findall(r'[\d.]+', metric_text.replace(',', ''))
            if numbers:
                value = float(numbers[0])
                if 'K' in metric_text.upper():
                    value *= 1000
                elif 'M' in metric_text.upper():
                    value *= 1000000
                return int(value)
            return 0
        except:
            return 0
    
    def _extract_video_urls(self, element) -> List[str]:
        """
        Extract video URLs from tweet element.
        
        Args:
            element: Tweet element (Selenium or Playwright)
            
        Returns:
            List of video URLs (may be empty)
        """
        video_urls = []
        try:
            # Try multiple selectors for video elements
            video_selectors = [
                'video source[src*="video.twimg.com"]',  # Preferred - source tags
                'video[src*="video.twimg.com"]',  # Fallback - direct video src
            ]
            
            for selector in video_selectors:
                try:
                    video_elements = element.find_elements(By.CSS_SELECTOR, selector)
                    for video in video_elements:
                        # Try src first, then data-src
                        src = video.get_attribute('src') or video.get_attribute('data-src')
                        if src and 'video.twimg.com' in src:
                            # Clean URL - get base URL without query params
                            base_url = src.split('?')[0]
                            
                            # For video URLs, try to get original quality
                            # Twitter video URLs may have quality indicators in path or params
                            if '?name=' in src or '?format=' in src:
                                # Already has quality params, use as-is
                                cleaned_url = src
                            else:
                                # Try to get original quality by adding ?name=orig
                                # This may not work for all videos, but worth trying
                                cleaned_url = base_url + '?name=orig'
                            
                            video_urls.append(cleaned_url)
                except Exception as e:
                    # Continue with next selector if this one fails
                    continue
            
            # Remove duplicates while preserving order
            seen = set()
            unique_video_urls = []
            for url in video_urls:
                # Use base URL without query params as key
                base_url = url.split('?')[0]
                if base_url not in seen:
                    seen.add(base_url)
                    unique_video_urls.append(url)
            
            return unique_video_urls
        except Exception as e:
            # If extraction fails, return empty list
            return []
    
    def _detect_show_more_link(self, element) -> tuple[bool, Optional[str]]:
        """
        Detect if tweet element contains a "Show more" link.
        
        Args:
            element: Tweet element (Selenium WebElement or PlaywrightElementWrapper)
        
        Returns:
            tuple[bool, Optional[str]]: 
                - bool: True if "Show more" link detected, False otherwise
                - Optional[str]: Tweet URL if link detected, None otherwise
        
        Implementation:
            - Searches for links with text matching "Show more" or "Show this thread"
            - Verifies link href contains "/status/" pattern
            - Returns (True, tweet_url) if both conditions met, (False, None) otherwise
        """
        try:
            # Find all links in the tweet element that point to status pages
            links = element.find_elements(By.CSS_SELECTOR, 'a[href*="/status/"]')
            
            for link in links:
                try:
                    link_text = link.text.strip().lower()
                    href = link.get_attribute('href')
                    
                    # Check if text matches "Show more" or "Show this thread" AND href is tweet URL
                    if href and '/status/' in href:
                        if 'show more' in link_text or 'show this thread' in link_text:
                            # Ensure it's a full URL (not relative)
                            if href.startswith('http'):
                                return True, href
                            elif href.startswith('/'):
                                # Convert relative URL to absolute
                                return True, f"https://x.com{href}"
                            else:
                                return True, href
                except:
                    continue
            
            return False, None
        except Exception as e:
            # Graceful degradation: return False on any error
            print(f"Error detecting 'Show more' link: {e}")
            return False, None
    
    def _calculate_navigation_delay(self, base_min: float = 2.0, base_max: float = 5.0) -> float:
        """
        Calculate delay with ±25% random variation.
        
        Args:
            base_min: Minimum base delay in seconds (default: 2.0)
            base_max: Maximum base delay in seconds (default: 5.0)
        
        Returns:
            float: Delay in seconds with random variation
        """
        import random
        base_delay = random.uniform(base_min, base_max)
        variation = base_delay * 0.25  # 25% variation
        random_variation = random.uniform(-variation, variation)
        return max(0.1, base_delay + random_variation)  # Ensure non-negative
    
    def _calculate_timeout(self, base_min: float = 10.0, base_max: float = 15.0) -> float:
        """
        Calculate timeout with ±25% random variation.
        
        Args:
            base_min: Minimum base timeout in seconds (default: 10.0)
            base_max: Maximum base timeout in seconds (default: 15.0)
        
        Returns:
            float: Timeout in seconds with random variation
        """
        import random
        base_timeout = random.uniform(base_min, base_max)
        variation = base_timeout * 0.25  # 25% variation
        random_variation = random.uniform(-variation, variation)
        return max(5.0, base_timeout + random_variation)  # Minimum 5 seconds
    
    def _fetch_full_tweet_text(self, tweet_url: str) -> Optional[str]:
        """
        Navigate to tweet detail page and extract full text.
        
        Args:
            tweet_url: Full URL to tweet detail page (e.g., https://x.com/username/status/1234567890)
        
        Returns:
            Optional[str]: Full tweet text if extraction successful, None if failed
        
        Implementation:
            - Navigates to tweet_url with configurable timeout (10-15s with ±25% variation)
            - Waits for tweet content to load
            - Extracts text using existing selector logic
            - Returns full text or None on failure
        """
        if not self.driver:
            return None
        
        try:
            # Calculate randomized timeout
            timeout_seconds = self._calculate_timeout(10.0, 15.0)
            timeout_ms = int(timeout_seconds * 1000)
            
            # Navigate to tweet detail page
            if self.use_playwright:
                self.driver.goto(tweet_url, wait_until="load", timeout=timeout_ms)
            else:
                self.driver.get(tweet_url)
            
            # Wait for page to load
            time.sleep(2)  # Allow dynamic content to render
            
            # Find the main tweet article
            if self.use_playwright:
                try:
                    self.driver.wait_for_selector('article[data-testid="tweet"]', timeout=int(timeout_seconds * 1000))
                    tweet_article_locator = self.driver.locator('article[data-testid="tweet"]').first
                except Exception:
                    return None
            else:
                try:
                    WebDriverWait(self.driver, int(timeout_seconds)).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
                    )
                    tweet_article = self.driver.find_element(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
                except TimeoutException:
                    return None
            
            # Extract text using existing selector logic (same as _extract_tweet_data)
            text_content = ""
            text_selectors = [
                '[data-testid="tweetText"]',
                'div[data-testid="tweetText"]',
                'span[data-testid="tweetText"]',
                'div[lang]',
                '[role="text"]',
                'div[dir="auto"]',
            ]
            
            for selector in text_selectors:
                try:
                    if self.use_playwright:
                        text_locator = tweet_article_locator.locator(selector).first
                        try:
                            text_content = text_locator.text_content() or ""
                        except:
                            continue
                    else:
                        text_element = tweet_article.find_element(By.CSS_SELECTOR, selector)
                        text_content = text_element.text if text_element else ""
                    
                    if text_content and len(text_content.strip()) > 0:
                        break
                except:
                    continue
            
            # If all selectors fail, try fallback extraction
            if not text_content or len(text_content.strip()) == 0:
                try:
                    if self.use_playwright:
                        all_text = tweet_article_locator.text_content() or ""
                    else:
                        all_text = tweet_article.text
                    
                    # Filter out metadata lines
                    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
                    content_lines = []
                    for line in lines:
                        if (len(line) < 3 or 
                            line.startswith('@') and len(line.split()) == 1 or
                            line.replace('.', '').replace(',', '').isdigit() or
                            '·' in line and len(line) < 20 or
                            'Replying to' in line or
                            'Show this thread' in line):
                            continue
                        content_lines.append(line)
                    
                    if content_lines:
                        text_content = ' '.join(sorted(content_lines, key=len, reverse=True)[:3])
                except:
                    pass
            
            return text_content.strip() if text_content else None
            
        except Exception as e:
            print(f"Error fetching full tweet text from {tweet_url}: {e}")
            return None
    
    def _fetch_full_tweet_text_with_retry(self, tweet_url: str) -> Optional[str]:
        """
        Fetch full text with exponential backoff retry for rate limiting.
        
        Args:
            tweet_url: Full URL to tweet detail page
        
        Returns:
            Optional[str]: Full tweet text if successful, None after all retries exhausted
        
        Retry Strategy:
            - Max retries: 5
            - Initial wait: 1.0 second
            - Max wait: 60.0 seconds
            - Backoff factor: 2.0
            - Handles: RateLimitError, TimeoutException, general Exception
        """
        from lists_app.services import retry_with_exponential_backoff
        
        def fetch_attempt():
            return self._fetch_full_tweet_text(tweet_url)
        
        try:
            return retry_with_exponential_backoff(
                fetch_attempt,
                max_retries=5,
                initial_wait=1.0,
                max_wait=60.0,
                backoff_factor=2.0,
                exceptions=(Exception,)
            )
        except Exception as e:
            # After all retries exhausted, return None (caller will use truncated text)
            print(f"Failed to fetch full text after retries: {e}")
            return None
    
    def _fetch_full_text_batch(self, tweets_needing_full_text: List[Dict]) -> None:
        """
        Batch navigate to tweet detail pages and extract full text.
        
        Args:
            tweets_needing_full_text: List of dicts with structure:
                [
                    {
                        'tweet_data': dict,  # Reference to tweet_data dict (will be updated)
                        'tweet_url': str,    # URL for navigation
                        'tweet_id': str       # For logging
                    },
                    ...
                ]
        
        Returns:
            None (modifies tweet_data dicts in-place)
        """
        if not tweets_needing_full_text:
            return
        
        print(f"Fetching full text for {len(tweets_needing_full_text)} tweets...")
        
        for i, tweet_ref in enumerate(tweets_needing_full_text):
            tweet_data = tweet_ref.get('tweet_data')
            tweet_url = tweet_ref.get('tweet_url')
            tweet_id = tweet_ref.get('tweet_id', 'unknown')
            
            if not tweet_data or not tweet_url:
                continue
            
            try:
                # Fetch full text with retry
                full_text = self._fetch_full_tweet_text_with_retry(tweet_url)
                
                if full_text:
                    # Update tweet_data with full text
                    tweet_data['text_content'] = full_text
                    print(f"✓ Fetched full text for tweet {tweet_id} ({len(full_text)} chars)")
                else:
                    print(f"✗ Failed to fetch full text for tweet {tweet_id}, using truncated text")
                    # tweet_data['text_content'] remains as truncated text (no change needed)
                
                # Add randomized delay before next navigation (except for last tweet)
                if i < len(tweets_needing_full_text) - 1:
                    delay = self._calculate_navigation_delay(2.0, 5.0)
                    time.sleep(delay)
                    
            except Exception as e:
                print(f"Error processing tweet {tweet_id} in batch: {e}")
                # Continue with next tweet even if this one fails
                continue
        
        print(f"Completed full text fetching for {len(tweets_needing_full_text)} tweets")
    
    def _fetch_profile_photo_from_page(self, username: str) -> str:
        """
        Fetch profile photo URL by navigating to the user's photo page.
        
        This method navigates to https://x.com/{username}/photo and extracts
        the actual profile image URL, which is more reliable than extracting
        from the tweet DOM.
        
        NOTE: This method navigates away from the current page. Only call it
        when you're done extracting data from the current page to avoid stale
        element references.
        
        Args:
            username: Twitter username (without @)
            
        Returns:
            Profile photo URL or empty string if not found
        """
        if not self.driver:
            return ''
        
        # Check cache first
        if username in self.profile_photo_cache:
            return self.profile_photo_cache[username]
        
        try:
            # Navigate to profile photo page
            photo_page_url = f"https://x.com/{username}/photo"
            print(f"Fetching profile photo from: {photo_page_url}")
            
            # Save current URL to return to it later
            current_url = self.driver.current_url
            
            # Navigate to photo page
            self.driver.get(photo_page_url)
            time.sleep(4)  # Wait for page to load (profile pages can be slow)
            
            # Handle cookie consent if it appears
            self._handle_cookie_consent()
            
            # Try multiple selectors to find the profile image
            # The photo page shows the profile picture, often in a modal or large view
            profile_img_selectors = [
                # Direct image selectors
                'img[src*="pbs.twimg.com"][src*="profile_images"]',
                'img[data-src*="pbs.twimg.com"][data-src*="profile_images"]',
                # Images in profile sections
                'div[data-testid="UserAvatar-Container-"] img[src*="profile_images"]',
                'div[role="img"] img[src*="profile_images"]',
                # Images in articles/tweets on the profile page
                'article img[src*="profile_images"]',
                'div[data-testid="tweet"] img[src*="profile_images"]',
                # Any image with profile_images
                'img[src*="profile_images"]',
            ]
            
            profile_image_url = ''
            for selector in profile_img_selectors:
                try:
                    imgs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    for img in imgs:
                        src = img.get_attribute('src') or img.get_attribute('data-src') or ''
                        if src and 'pbs.twimg.com' in src and 'profile_images' in src:
                            # Get base URL without query params
                            base_url = src.split('?')[0]
                            
                            # Remove size suffixes to get the base filename
                            # Twitter profile images can have: _normal, _bigger, _mini, _200x200, _400x400, etc.
                            # We want the original without size suffix
                            size_suffixes = ['_normal', '_bigger', '_mini', '_200x200', '_400x400', '_original']
                            for suffix in size_suffixes:
                                if suffix in base_url:
                                    # Remove the suffix but keep the file extension
                                    # e.g., X62jsKbu_normal.jpg -> X62jsKbu.jpg
                                    base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                    break
                            
                            # Construct URL with ?name=orig for full resolution
                            # Only add ?name=orig if we successfully removed the size suffix
                            # or if there was no size suffix to begin with
                            profile_image_url = base_url + '?name=orig'
                            print(f"Found profile photo URL from photo page: {profile_image_url}")
                            break
                    
                    if profile_image_url:
                        break
                except Exception as e:
                    continue
            
            # If we still don't have a URL, try to find it in the page source
            if not profile_image_url:
                try:
                    page_source = self.driver.page_source
                    # Look for profile_images URLs in the page source
                    matches = re.findall(r'https://pbs\.twimg\.com/profile_images/[^"\s]+', page_source)
                    for match in matches:
                        if 'profile_images' in match and 'pbs.twimg.com' in match:
                            base_url = match.split('?')[0]
                            # Remove size suffixes
                            for suffix in ['_normal', '_bigger', '_mini', '_200x200', '_400x400']:
                                if suffix in base_url:
                                    base_url = re.sub(rf'{re.escape(suffix)}(\.\w+)$', r'\1', base_url)
                                    break
                            profile_image_url = base_url + '?name=orig'
                            print(f"Found profile photo URL from page source: {profile_image_url}")
                            break
                except:
                    pass
            
            # Cache the result
            if profile_image_url:
                self.profile_photo_cache[username] = profile_image_url
            
            # Don't return to original page - let the caller handle navigation
            # This avoids unnecessary navigation if we're fetching multiple photos
            
            return profile_image_url
            
        except Exception as e:
            print(f"Error fetching profile photo from page for {username}: {e}")
            # Try to return to original page
            try:
                if 'current_url' in locals() and current_url:
                    self.driver.get(current_url)
            except:
                pass
            return ''
    
    def get_home_timeline(self, max_tweets: int = 100) -> List[Dict]:
        """Scrape home timeline tweets from Twitter - supports both Selenium and Playwright."""
        if not self.driver:
            if not self.login():
                raise Exception("Failed to login to Twitter")
        
        tweets = []
        seen_tweet_ids = set()  # Track seen tweets by ID to avoid duplicates
        
        print("Navigating to home timeline...")
        # Use appropriate method based on browser type
        if self.use_playwright:
            self.driver.goto("https://x.com/home")
        else:
            self.driver.get("https://x.com/home")
        time.sleep(5)
        
        # Handle cookie consent banner if it appears
        self._handle_cookie_consent()
        
        # Wait for initial content to load
        try:
            if self.use_playwright:
                self.driver.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
                print("Home timeline loaded")
            else:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
                )
                print("Home timeline loaded")
        except (TimeoutException, Exception) as e:
            print("Warning: No tweets found initially, continuing anyway...")
        
        # Scroll and collect tweets
        last_height = self._execute_js("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scrolls = 50
        no_new_tweets_count = 0
        max_no_new_tweets = 5  # Stop if no new tweets found after 5 scrolls
        
        max_limit = max_tweets if max_tweets > 0 else float('inf')
        print(f"Starting to collect tweets (max: {'all' if max_tweets == 0 else max_tweets})...")
        
        while len(tweets) < max_limit and scroll_attempts < max_scrolls:
            # Find all tweet articles
            tweet_elements = self._find_tweet_elements()
            print(f"Found {len(tweet_elements)} tweet elements on page, currently have {len(tweets)} unique tweets")
            
            new_tweets_this_scroll = 0
            for element in tweet_elements:
                try:
                    # Wrap Playwright locators to work with _extract_tweet_data
                    if self.use_playwright:
                        from twitter.services_playwright_helpers import PlaywrightElementWrapper
                        wrapped_element = PlaywrightElementWrapper(element)
                    else:
                        wrapped_element = element
                    
                    tweet_data = self._extract_tweet_data(wrapped_element)
                    if tweet_data and tweet_data.get('tweet_id'):
                        tweet_id = tweet_data['tweet_id']
                        if tweet_id not in seen_tweet_ids:
                            seen_tweet_ids.add(tweet_id)
                            tweets.append(tweet_data)
                            new_tweets_this_scroll += 1
                except Exception as e:
                    print(f"Error extracting tweet: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
            
            # Check if we got new tweets
            if new_tweets_this_scroll == 0:
                no_new_tweets_count += 1
                print(f"No new tweets this scroll ({no_new_tweets_count}/{max_no_new_tweets})")
                if no_new_tweets_count >= max_no_new_tweets:
                    print(f"No new tweets found after {max_no_new_tweets} scrolls. Reached end of timeline.")
                    break
            else:
                no_new_tweets_count = 0
                print(f"Added {new_tweets_this_scroll} new tweets (total: {len(tweets)})")
            
            # Scroll down smoothly - multiple scrolls to trigger lazy loading
            self._execute_js("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Wait for new content to load
            
            # Additional scroll to trigger more content
            self._execute_js("window.scrollBy(0, 1000);")
            time.sleep(1)
            
            # Check if we've reached the bottom
            new_height = self._execute_js("return document.body.scrollHeight")
            scroll_position = self._execute_js("return window.pageYOffset + window.innerHeight")
            
            if new_height == last_height and scroll_position >= new_height - 100:
                # We're at the bottom and page height hasn't changed
                scroll_attempts += 1
                print(f"At bottom of page (scroll attempt {scroll_attempts}/{max_scrolls})")
            else:
                scroll_attempts = 0
                print(f"Page loaded more content (height: {new_height}, scroll: {scroll_position})")
            
            last_height = new_height
            
            # Progress update every 10 tweets
            if len(tweets) > 0 and len(tweets) % 10 == 0:
                print(f"Progress: {len(tweets)} tweets collected so far...")
        
        print(f"Finished collecting {len(tweets)} unique tweets")
        
        # Post-processing: Fetch full text for tweets with "Show more" links
        # Collect tweets needing full text during extraction
        tweets_needing_full_text = []
        for tweet in tweets:
            if tweet.get('needs_full_text', False) and tweet.get('tweet_url'):
                tweets_needing_full_text.append({
                    'tweet_data': tweet,
                    'tweet_url': tweet['tweet_url'],
                    'tweet_id': tweet.get('tweet_id', 'unknown')
                })
        
        # Batch navigate to detail pages and fetch full text
        if tweets_needing_full_text:
            try:
                print(f"Found {len(tweets_needing_full_text)} tweets with 'Show more' links, fetching full text...")
                self._fetch_full_text_batch(tweets_needing_full_text)
            except Exception as e:
                print(f"Error during full text batch fetching: {e}")
                import traceback
                traceback.print_exc()
                # Continue - truncated text will be used as fallback
        
        # Post-processing: Fetch missing profile photos for usernames that don't have them
        print("Fetching missing profile photos...")
        usernames_needing_photos = set()
        for tweet in tweets:
            username = tweet.get('author_username', '')
            profile_photo = tweet.get('author_profile_image_url', '')
            if username and not profile_photo and username not in self.profile_photo_cache:
                usernames_needing_photos.add(username)
        
        # Fetch profile photos in batch
        for username in usernames_needing_photos:
            try:
                profile_photo_url = self._fetch_profile_photo_from_page(username)
                if profile_photo_url:
                    self.profile_photo_cache[username] = profile_photo_url
                    # Update all tweets for this username
                    for tweet in tweets:
                        if tweet.get('author_username') == username and not tweet.get('author_profile_image_url'):
                            tweet['author_profile_image_url'] = profile_photo_url
            except Exception as e:
                print(f"Warning: Could not fetch profile photo for {username}: {e}")
                continue
        
        return tweets[:max_tweets] if max_tweets > 0 else tweets
    
    def get_tweet_thread(self, tweet_id: str) -> List[Dict]:
        """Get full thread for a tweet."""
        if not self.driver:
            if not self.login():
                raise Exception("Failed to login to Twitter")
        
        self.driver.get(f"https://x.com/i/web/status/{tweet_id}")
        time.sleep(3)
        
        thread_tweets = []
        # Find all tweets in the thread
        tweet_elements = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        
        for element in tweet_elements:
            tweet_data = self._extract_tweet_data(element)
            if tweet_data:
                thread_tweets.append(tweet_data)
        
        return thread_tweets
    
    def close(self):
        """Close the browser and ensure all async operations are complete."""
        print(f"[CLEANUP] Closing scraper (use_playwright={self.use_playwright})...")
        
        if self.use_playwright:
            # Close Playwright resources in proper order: page -> context -> browser -> playwright
            # This order is important to avoid resource leaks
            
            # 1. Close page first
            if self.driver:
                try:
                    print(f"[CLEANUP] Closing Playwright page...")
                    self.driver.close()
                except Exception as e:
                    print(f"[CLEANUP] Error closing Playwright page: {e}")
                finally:
                    self.driver = None
            
            # 2. Close context (contains all pages)
            if self.context:
                try:
                    print(f"[CLEANUP] Closing Playwright context...")
                    self.context.close()
                except Exception as e:
                    print(f"[CLEANUP] Error closing Playwright context: {e}")
                finally:
                    self.context = None
            
            # 3. Close browser (contains all contexts)
            if self.browser:
                try:
                    print(f"[CLEANUP] Closing Playwright browser...")
                    self.browser.close()
                except Exception as e:
                    print(f"[CLEANUP] Error closing Playwright browser: {e}")
                finally:
                    self.browser = None
            
            # 4. Stop Playwright process (this kills all browser processes)
            if self.playwright:
                try:
                    print(f"[CLEANUP] Stopping Playwright process...")
                    self.playwright.stop()
                except Exception as e:
                    print(f"[CLEANUP] Error stopping Playwright: {e}")
                finally:
                    self.playwright = None
            
            print(f"[CLEANUP] Playwright cleanup complete")
        else:
            # Close Selenium driver
            if self.driver:
                try:
                    print(f"[CLEANUP] Closing Selenium driver...")
                    self.driver.quit()
                except Exception as e:
                    print(f"[CLEANUP] Error closing Selenium driver: {e}")
                finally:
                    self.driver = None
            print(f"[CLEANUP] Selenium cleanup complete")
        
        # Force cleanup of any remaining references (defensive)
        self.driver = None
        self.browser = None
        self.context = None
        self.playwright = None
    
    def get_session_cookies(self) -> List[Dict]:
        """Get current session cookies for reuse."""
        if self.driver and not self.use_playwright:
            return self.driver.get_cookies()
        return self.session_cookies or []


class TwikitScraper:
    """Alternative scraper using Twikit library."""
    
    def __init__(self, username: str, password: Optional[str] = None, cookies: Optional[Dict] = None):
        self.username = username
        self.password = password
        self.cookies = cookies
        self.client = None
        
    def login(self):
        """Login using Twikit."""
        try:
            from twikit import Client
            
            self.client = Client()
            
            if self.cookies:
                # Use cookies if available
                self.client.set_cookies(self.cookies)
            elif self.password:
                # Login with credentials
                self.client.login(
                    username=self.username,
                    password=self.password
                )
            else:
                return False
            
            return True
        except ImportError:
            raise ImportError("Twikit not installed. Install with: pip install twikit")
        except Exception as e:
            print(f"Twikit login failed: {e}")
            return False
    
    def get_bookmarks(self, max_bookmarks: int = 100) -> List[Dict]:
        """Get bookmarks using Twikit."""
        if not self.client:
            if not self.login():
                raise Exception("Failed to login with Twikit")
        
        try:
            bookmarks = []
            user = self.client.get_user_by_screen_name(self.username)
            # Note: Twikit may have different methods for bookmarks
            # This is a placeholder - actual implementation depends on Twikit API
            bookmarks_response = user.get_bookmarks()
            
            for bookmark in bookmarks_response[:max_bookmarks]:
                bookmarks.append({
                    'tweet_id': bookmark.id,
                    'author_username': bookmark.user.screen_name,
                    'text_content': bookmark.full_text,
                    'created_at': bookmark.created_at,
                    'like_count': bookmark.favorite_count,
                    'retweet_count': bookmark.retweet_count,
                    'reply_count': bookmark.reply_count,
                    'media_urls': [media.media_url for media in bookmark.media] if bookmark.media else [],
                    'is_reply': bookmark.in_reply_to_status_id is not None,
                    'url': f"https://x.com/{bookmark.user.screen_name}/status/{bookmark.id}",
                })
            
            return bookmarks
        except Exception as e:
            print(f"Error getting bookmarks with Twikit: {e}")
            return []

