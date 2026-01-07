"""
Services for fetching Twitter lists and grouping tweets into events.
"""
import time
import re
import logging
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime, date, timedelta
from django.utils import timezone
from django.db import transaction
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from twitter.services import TwitterScraper
from twitter.models import TwitterProfile, Tweet
from .models import TwitterList, ListTweet, Event, EventTweet

logger = logging.getLogger(__name__)

# Constants for ListsService
DEFAULT_PAGE_LOAD_WAIT = 5  # seconds
DEFAULT_LIST_PROCESSING_DELAY = 1.0  # seconds between list processing
DEFAULT_RETRY_MAX_RETRIES = 3
DEFAULT_RETRY_INITIAL_WAIT = 2.0  # seconds
DEFAULT_RETRY_MAX_WAIT = 30.0  # seconds
DEFAULT_RETRY_BACKOFF_FACTOR = 2.0
DEFAULT_SCROLL_WAIT = 2  # seconds
MAX_SCROLL_ATTEMPTS = 10
MIN_SCROLL_STABLE_ATTEMPTS = 3
LISTS_PAGE_LOAD_TIMEOUT = 15  # seconds


def retry_with_exponential_backoff(
    func: Callable,
    max_retries: int = 5,
    initial_wait: float = 1.0,
    max_wait: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Retry a function with exponential backoff.
    
    Args:
        func: The function to retry
        max_retries: Maximum number of retry attempts
        initial_wait: Initial wait time in seconds
        max_wait: Maximum wait time in seconds
        backoff_factor: Factor to multiply wait time by on each retry
        exceptions: Tuple of exceptions to catch and retry on
    
    Returns:
        The result of the function call
    """
    wait_time = initial_wait
    
    for attempt in range(max_retries + 1):
        try:
            return func()
        except exceptions as e:
            if attempt == max_retries:
                # Last attempt failed, raise the exception
                raise
            
            # Check if it's a 429 error (rate limiting)
            error_msg = str(e).lower()
            is_rate_limit = '429' in error_msg or 'rate limit' in error_msg or 'too many requests' in error_msg
            
            if is_rate_limit:
                logger.warning(f"Rate limit detected (429), waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}...")
            else:
                logger.warning(f"Error occurred, waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}...")
            
            time.sleep(wait_time)
            
            # Exponential backoff: increase wait time for next retry
            wait_time = min(wait_time * backoff_factor, max_wait)
    
    # Should never reach here, but just in case
    raise Exception("Retry logic failed unexpectedly")


class ListsService:
    """
    Service for fetching and managing Twitter lists.
    
    This service handles:
    - Fetching user's Twitter lists
    - Syncing list tweets
    - Managing list data in the database
    """
    
    def __init__(self, twitter_profile: TwitterProfile, use_playwright: bool = False):
        """
        Initialize the ListsService.
        
        Args:
            twitter_profile: TwitterProfile instance with credentials
            use_playwright: Whether to use Playwright instead of Selenium
            
        Raises:
            ValueError: If Twitter credentials are not available
        """
        self.twitter_profile = twitter_profile
        credentials = twitter_profile.get_credentials()
        if not credentials:
            raise ValueError("Twitter credentials not available")
        
        self.scraper = TwitterScraper(
            username=credentials.get('username'),
            password=credentials.get('password'),
            cookies=credentials.get('cookies'),
            use_playwright=use_playwright
        )
        self.use_playwright = use_playwright
        self.cookie_consent_handled = False  # Track if cookie consent has been handled
    
    def _find_elements(self, selector, by=By.CSS_SELECTOR):
        """Find elements - works with both Selenium and Playwright."""
        if self.use_playwright:
            if by == By.CSS_SELECTOR or by == 'css selector':
                return self.scraper.driver.locator(selector).all()
            elif by == By.XPATH or by == 'xpath':
                return self.scraper.driver.locator(f'xpath={selector}').all()
            else:
                raise ValueError(f"Unsupported selector type: {by}")
        else:
            return self.scraper.driver.find_elements(by, selector)
    
    def _execute_script(self, script, *args):
        """Execute JavaScript - works with both Selenium and Playwright."""
        if self.use_playwright:
            # Playwright evaluate - convert script and args
            if args:
                # For scripts with arguments, use evaluate with function
                func_script = f"({script})"
                return self.scraper.driver.evaluate(func_script, args[0] if len(args) == 1 else args)
            else:
                # Remove 'return' if present for Playwright
                script = script.strip()
                if script.startswith('return '):
                    script = script[7:].strip()
                return self.scraper.driver.evaluate(script)
        else:
            return self.scraper.driver.execute_script(script, *args)
    
    def _get_current_url(self):
        """Get current URL - works with both Selenium and Playwright."""
        if self.use_playwright:
            return self.scraper.driver.url
        else:
            return self.scraper.driver.current_url
    
    def _navigate_to(self, url):
        """Navigate to URL - works with both Selenium and Playwright."""
        if self.use_playwright:
            self.scraper.driver.goto(url)
        else:
            self.scraper.driver.get(url)
    
    def _go_back(self):
        """Go back - works with both Selenium and Playwright."""
        if self.use_playwright:
            self.scraper.driver.go_back()
        else:
            self.scraper.driver.back()
    
    def _get_text(self, element):
        """Get element text - works with both Selenium and Playwright."""
        if self.use_playwright:
            return element.text_content() if hasattr(element, 'text_content') else str(element)
        else:
            return element.text if hasattr(element, 'text') else str(element)
    
    def _click(self, element):
        """Click element - works with both Selenium and Playwright."""
        # Both use .click() but Playwright locators need to be awaited in async context
        # Since we're in sync context, just call click directly
        element.click()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        self.close()
    
    def close(self):
        """
        Close the scraper and clean up resources.
        
        Should be called when done with the service to free browser resources.
        """
        if self.scraper:
            try:
                self.scraper.close()
            except Exception as e:
                logger.error(f"Error closing scraper: {e}", exc_info=True)
            finally:
                self.scraper = None
    
    def get_user_lists(self) -> List[Dict]:
        """
        Fetch all lists that the user owns or subscribes to.
        
        Process:
        1. Navigate to lists page
        2. Wait for lists to load
        3. Scroll to load all lists
        4. Extract list information
        5. Process lists that need clicking
        
        Returns:
            List of dictionaries containing list_id, list_name, list_url, list_slug
        """
        if not self.scraper.driver:
            if not self.scraper.login():
                raise Exception("Failed to login to Twitter")
        
        lists = []
        seen_list_ids = set()
        
        try:
            self._navigate_to_lists_page()
            self._wait_for_lists_to_load()
            self._scroll_to_load_all_lists()
            
            list_cells = self._find_list_cells()
            if not list_cells:
                logger.warning("No list cells found")
                return []
            
            list_names = self._extract_list_names(list_cells)
            lists = self._process_lists(list_names, seen_list_ids)
            
        except Exception as e:
            logger.error(f"Error fetching user lists: {e}", exc_info=True)
            raise Exception(f"Failed to fetch user lists: {e}")
        
        return lists
    
    def _navigate_to_lists_page(self):
        """Navigate to the user's lists page with retry logic."""
        logger.info("Navigating to lists page...")
        username = self.twitter_profile.twitter_username
        lists_url = f"https://x.com/{username}/lists"
        logger.info(f"Fetching lists from: {lists_url}")
        
        def navigate():
            self._navigate_to(lists_url)
            time.sleep(DEFAULT_PAGE_LOAD_WAIT)
            return True
        
        retry_with_exponential_backoff(
            navigate,
            max_retries=DEFAULT_RETRY_MAX_RETRIES,
            initial_wait=DEFAULT_RETRY_INITIAL_WAIT,
            max_wait=DEFAULT_RETRY_MAX_WAIT,
            backoff_factor=DEFAULT_RETRY_BACKOFF_FACTOR
        )
        
        # Handle cookie consent only once per session
        if not self.cookie_consent_handled:
            self.scraper._handle_cookie_consent()
            self.cookie_consent_handled = True
    
    def _wait_for_lists_to_load(self):
        """Wait for list cells to appear on the page."""
        logger.info("Waiting for lists page to load...")
        try:
            if self.scraper.use_playwright:
                self.scraper.driver.wait_for_selector(
                    'div[data-testid="listCell"]', 
                    timeout=LISTS_PAGE_LOAD_TIMEOUT * 1000
                )
            else:
                wait = WebDriverWait(self.scraper.driver, LISTS_PAGE_LOAD_TIMEOUT)
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="listCell"]')))
            logger.info("Lists page loaded")
        except Exception as e:
            logger.warning(f"Lists may not have loaded: {e}")
    
    def _scroll_to_load_all_lists(self):
        """Scroll the page to trigger lazy loading of all lists."""
        logger.info("Scrolling to load all lists...")
        last_height = 0
        scroll_attempts = 0
        no_change_count = 0
        max_no_change = 5  # Require 5 consecutive no-changes before stopping
        
        # Count initial lists before scrolling
        initial_cells = self._find_elements('div[data-testid="listCell"]', By.CSS_SELECTOR)
        if self.use_playwright:
            initial_cells = list(initial_cells)
        initial_count = len(initial_cells)
        logger.info(f"Found {initial_count} lists before scrolling")
        
        while scroll_attempts < MAX_SCROLL_ATTEMPTS:
            if self.use_playwright:
                current_height = self.scraper.driver.evaluate("document.body.scrollHeight")
                self.scraper.driver.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            else:
                current_height = self.scraper.driver.execute_script("return document.body.scrollHeight")
                self.scraper.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            
            time.sleep(DEFAULT_SCROLL_WAIT)
            
            # Check if new lists loaded by counting cells
            current_cells = self._find_elements('div[data-testid="listCell"]', By.CSS_SELECTOR)
            if self.use_playwright:
                current_cells = list(current_cells)
            current_count = len(current_cells)
            
            if current_height == last_height and current_count == initial_count:
                no_change_count += 1
                if no_change_count >= max_no_change:
                    logger.info(f"Stopped scrolling after {scroll_attempts} attempts - no new lists loaded (found {current_count} total)")
                    break
            else:
                no_change_count = 0
                if current_count > initial_count:
                    logger.info(f"Found {current_count} lists (was {initial_count}) - continuing to scroll...")
                    initial_count = current_count
            
            scroll_attempts += 1
            last_height = current_height
        
        # Final count
        final_cells = self._find_elements('div[data-testid="listCell"]', By.CSS_SELECTOR)
        if self.use_playwright:
            final_cells = list(final_cells)
        final_count = len(final_cells)
        logger.info(f"Finished scrolling - found {final_count} total list cells")
        
        # Scroll back to top
        if self.use_playwright:
            self.scraper.driver.evaluate("window.scrollTo(0, 0)")
        else:
            self.scraper.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(DEFAULT_SCROLL_WAIT)  # Wait for page to settle
    
    def _find_your_lists_heading(self):
        """Find the 'Your Lists' heading element."""
        try:
            xpath_selector = "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'your lists')]"
            headings = self._find_elements(xpath_selector, By.XPATH)
            if self.use_playwright:
                headings = list(headings)
            for heading in headings:
                heading_text = self._get_text(heading).strip().lower()
                if 'your lists' in heading_text and 'discover' not in heading_text:
                    logger.info("Found 'Your Lists' heading")
                    return heading
        except Exception as e:
            logger.warning(f"Could not find 'Your Lists' heading: {e}")
        return None
    
    def _filter_list_cells_by_section(self, all_cells: List, your_lists_heading) -> List:
        """
        Filter list cells to only those in the 'Your Lists' section.
        
        Args:
            all_cells: All list cell elements found on the page
            your_lists_heading: The 'Your Lists' heading element, or None
            
        Returns:
            Filtered list of cells in 'Your Lists' section
        """
        list_cells = []
        if your_lists_heading:
            try:
                # Get heading position
                if self.use_playwright:
                    heading_box = your_lists_heading.bounding_box() if hasattr(your_lists_heading, 'bounding_box') else None
                    heading_y = heading_box['y'] if heading_box else 0
                else:
                    heading_y = self._execute_script("return arguments[0].getBoundingClientRect().top;", your_lists_heading)
                
                # Include cells below the heading
                for cell in all_cells:
                    try:
                        if self.use_playwright:
                            cell_box = cell.bounding_box() if hasattr(cell, 'bounding_box') else None
                            cell_y = cell_box['y'] if cell_box else 0
                        else:
                            cell_y = self._execute_script("return arguments[0].getBoundingClientRect().top;", cell)
                        
                        # Include if below heading (with small margin)
                        if cell_y > (heading_y - 100):
                            cell_text = self._get_text(cell).strip().lower()
                            # Skip obvious "Discover" lists (have "followers including" but not "Created by")
                            if 'followers including' in cell_text and 'created by' not in cell_text:
                                # Only skip if in first few cells (Discover section is at top)
                                if len(list_cells) < 3:
                                    continue
                            list_cells.append(cell)
                    except:
                        # If we can't check position, include it anyway
                        list_cells.append(cell)
            except Exception as e:
                logger.warning(f"Error filtering by position: {e}, using all cells")
                list_cells = all_cells
        else:
            # No heading found, use text-based filtering
            logger.warning("'Your Lists' heading not found, using text-based filtering...")
            for cell in all_cells:
                try:
                    cell_text = self._get_text(cell).strip().lower()
                    # Skip "Discover" lists
                    if 'followers including' in cell_text and 'created by' not in cell_text:
                        continue
                    list_cells.append(cell)
                except:
                    # Include if we can't check
                    list_cells.append(cell)
        
        return list_cells
    
    def _find_list_cells(self) -> List:
        """
        Find all list cells on the page, filtered to 'Your Lists' section.
        
        Returns:
            List of list cell elements
        """
        logger.info("Finding list cells on page...")
        
        # Find all list cells
        all_cells = self._find_elements('div[data-testid="listCell"]', By.CSS_SELECTOR)
        if self.use_playwright:
            all_cells = list(all_cells)
        
        logger.info(f"Found {len(all_cells)} total list cells")
        
        if not all_cells:
            return []
        
        # Find "Your Lists" heading to filter cells
        your_lists_heading = self._find_your_lists_heading()
        
        # Filter cells to only those in "Your Lists" section
        list_cells = self._filter_list_cells_by_section(all_cells, your_lists_heading)
        
        logger.info(f"Filtered to {len(list_cells)} cells in 'Your Lists' section")
        
        return list_cells
    
    def _extract_list_names(self, list_cells: List) -> List[Dict]:
        """
        Extract list names and URLs from list cells.
        
        Args:
            list_cells: List of cell elements containing list information
            
        Returns:
            List of dictionaries with list name, id, url, and needs_click flag
        """
        logger.info(f"Extracting list names from {len(list_cells)} cells...")
        list_names = []
        for idx, cell in enumerate(list_cells, 1):
            try:
                # Extract list name from cell IMMEDIATELY (before it becomes stale)
                cell_text = self._get_text(cell).strip()
                if not cell_text:
                    continue
                
                # Parse list name (first line, before · or metadata)
                lines = cell_text.split('\n')
                first_line = lines[0].strip() if lines else ""
                
                if '·' in first_line:
                    list_name = first_line.split('·')[0].strip()
                else:
                    # Extract name before words like "members", "followers"
                    parts = first_line.split()
                    name_parts = []
                    for part in parts:
                        if part.lower() in ['members', 'followers', 'member', 'follower', '·']:
                            break
                        name_parts.append(part)
                    list_name = ' '.join(name_parts).strip() if name_parts else first_line
                
                if list_name and len(list_name) >= 2:
                    # Also try to extract URL directly if available - use multiple strategies
                    list_url = None
                    list_id = None
                    
                    # Strategy 1: Look for links with /i/lists/ pattern
                    try:
                        if self.use_playwright:
                            links = cell.locator('a[href*="/i/lists/"]').all()
                            if links:
                                for link in links:
                                    try:
                                        href = link.get_attribute('href') or link.evaluate('el => el.href')
                                        if href:
                                            match = re.search(r'/i/lists/(\d+)', href)
                                            if match:
                                                list_id = match.group(1)
                                                list_url = href if href.startswith('http') else f"https://x.com{href}"
                                                break
                                    except:
                                        continue
                        else:
                            links = cell.find_elements(By.CSS_SELECTOR, 'a[href*="/i/lists/"]')
                            if links:
                                for link in links:
                                    try:
                                        href = link.get_attribute('href')
                                        if href:
                                            match = re.search(r'/i/lists/(\d+)', href)
                                            if match:
                                                list_id = match.group(1)
                                                list_url = href if href.startswith('http') else f"https://x.com{href}"
                                                break
                                    except:
                                        continue
                    except:
                        pass
                    
                    # Strategy 2: Look for ANY links in the cell and check if they contain /lists/
                    if not list_id:
                        try:
                            if self.use_playwright:
                                all_links = cell.locator('a[href]').all()
                                for link in all_links:
                                    try:
                                        href = link.get_attribute('href') or link.evaluate('el => el.href')
                                        if href and '/lists/' in href and '/i/lists/' in href:
                                            match = re.search(r'/i/lists/(\d+)', href)
                                            if match:
                                                list_id = match.group(1)
                                                list_url = href if href.startswith('http') else f"https://x.com{href}"
                                                break
                                    except:
                                        continue
                            else:
                                all_links = cell.find_elements(By.CSS_SELECTOR, 'a[href]')
                                for link in all_links:
                                    try:
                                        href = link.get_attribute('href')
                                        if href and '/lists/' in href and '/i/lists/' in href:
                                            match = re.search(r'/i/lists/(\d+)', href)
                                            if match:
                                                list_id = match.group(1)
                                                list_url = href if href.startswith('http') else f"https://x.com{href}"
                                                break
                                    except:
                                        continue
                        except:
                            pass
                    
                    # Strategy 3: Extract from HTML if available
                    if not list_id:
                        try:
                            if self.use_playwright:
                                html = cell.inner_html() if hasattr(cell, 'inner_html') else ''
                            else:
                                html = cell.get_attribute('outerHTML') or ''
                            
                            if html:
                                # Look for href patterns in HTML
                                matches = re.findall(r'href=["\']([^"\']*\/i\/lists\/\d+[^"\']*)["\']', html)
                                if matches:
                                    href = matches[0]
                                    match = re.search(r'/i/lists/(\d+)', href)
                                    if match:
                                        list_id = match.group(1)
                                        list_url = href if href.startswith('http') else f"https://x.com{href}"
                        except:
                            pass
                    
                    # Store cell index for re-finding later
                    list_names.append({
                        'name': list_name,
                        'list_id': list_id,
                        'list_url': list_url,
                        'needs_click': list_id is None,
                        'cell_index': idx - 1,  # Store original index (0-based)
                    })
                    if list_id:
                        logger.debug(f"[{idx}/{len(list_cells)}] '{list_name}' - URL found directly: {list_id}")
                    else:
                        logger.debug(f"[{idx}/{len(list_cells)}] '{list_name}' - will need to click")
            except Exception as e:
                logger.warning(f"[{idx}/{len(list_cells)}] Error extracting name: {e}")
                continue
        
        logger.info(f"Extracted {len(list_names)} list names")
        direct_urls = sum(1 for d in list_names if not d['needs_click'])
        logger.info(f"{direct_urls} have URLs directly, {len(list_names) - direct_urls} need clicking")
        
        return list_names
    
    def _process_lists(self, list_names: List[Dict], seen_list_ids: set) -> List[Dict]:
        """
        Process lists, clicking those that need it to get URLs.
        
        Args:
            list_names: List of dictionaries with list information
            seen_list_ids: Set of already seen list IDs to avoid duplicates
            
        Returns:
            List of dictionaries with complete list information
        """
        lists = []
        logger.info(f"Processing {len(list_names)} lists (in reverse order to avoid stale elements)...")
        
        for idx, list_data in enumerate(reversed(list_names), 1):
            actual_idx = len(list_names) - idx + 1
            list_name = list_data['name']
            list_id = list_data.get('list_id')
            list_url = list_data.get('list_url')
            
            # Add a small delay between processing lists to avoid rate limiting
            if idx > 1:  # Don't delay before the first list
                time.sleep(DEFAULT_LIST_PROCESSING_DELAY)
            
            logger.debug(f"[{actual_idx}/{len(list_names)}] Processing: '{list_name}'")
            
            # If we already have the URL, use it
            if list_id and list_url:
                if list_id not in seen_list_ids:
                    seen_list_ids.add(list_id)
                    lists.append({
                        'list_id': list_id,
                        'list_name': list_name,
                        'list_url': list_url,
                        'list_slug': '',
                    })
                    logger.info(f"Added (direct URL): '{list_name}' (ID: {list_id})")
                else:
                    logger.debug(f"Skipping duplicate: '{list_name}' (ID: {list_id})")
                continue
            
            # Need to click to get URL
            logger.debug(f"Clicking '{list_name}' to get URL...")
            try:
                # Make sure we're on the lists page
                current_url = self._get_current_url()
                if '/lists/' not in current_url or not current_url.endswith('/lists'):
                    username = self.twitter_profile.twitter_username
                    self._navigate_to(f"https://x.com/{username}/lists")
                    time.sleep(3)
                
                # Scroll back to top to ensure all cells are accessible
                if self.use_playwright:
                    self.scraper.driver.evaluate("window.scrollTo(0, 0)")
                else:
                    self.scraper.driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)  # Wait longer for page to stabilize
                
                # Re-find "Your Lists" heading and filter cells again (page might have changed)
                your_lists_heading_refresh = None
                try:
                    xpath_selector = "//*[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'your lists')]"
                    headings = self._find_elements(xpath_selector, By.XPATH)
                    if self.use_playwright:
                        headings = list(headings)
                    for heading in headings:
                        heading_text = self._get_text(heading).strip().lower()
                        if 'your lists' in heading_text and 'discover' not in heading_text:
                            your_lists_heading_refresh = heading
                            break
                except:
                    pass
                
                # Re-find all cells with retry logic
                def find_cells():
                    cells = self._find_elements('div[data-testid="listCell"]', By.CSS_SELECTOR)
                    if self.use_playwright:
                        cells = list(cells)
                    return cells
                
                try:
                    all_cells_refresh = retry_with_exponential_backoff(
                        find_cells,
                        max_retries=3,
                        initial_wait=1.0,
                        max_wait=15.0,
                        backoff_factor=2.0
                    )
                except:
                    # If retries fail, try once more without retry
                    all_cells_refresh = self._find_elements('div[data-testid="listCell"]', By.CSS_SELECTOR)
                    if self.use_playwright:
                        all_cells_refresh = list(all_cells_refresh)
                
                # Re-filter to "Your Lists" section if heading found
                if your_lists_heading_refresh and len(all_cells_refresh) > 0:
                    try:
                        if self.use_playwright:
                            heading_box = your_lists_heading_refresh.bounding_box() if hasattr(your_lists_heading_refresh, 'bounding_box') else None
                            heading_y = heading_box['y'] if heading_box else 0
                        else:
                            heading_y = self._execute_script("return arguments[0].getBoundingClientRect().top;", your_lists_heading_refresh)
                        
                        filtered_cells = []
                        for c in all_cells_refresh:
                            try:
                                if self.use_playwright:
                                    cell_box = c.bounding_box() if hasattr(c, 'bounding_box') else None
                                    cell_y = cell_box['y'] if cell_box else 0
                                else:
                                    cell_y = self._execute_script("return arguments[0].getBoundingClientRect().top;", c)
                                
                                if cell_y > (heading_y - 100):
                                    cell_text = self._get_text(c).strip().lower()
                                    if 'followers including' in cell_text and 'created by' not in cell_text:
                                        if len(filtered_cells) < 3:
                                            continue
                                    filtered_cells.append(c)
                            except:
                                filtered_cells.append(c)
                        
                        if len(filtered_cells) > 0:
                            all_cells_refresh = filtered_cells
                            print(f"    Re-filtered to {len(all_cells_refresh)} cells in 'Your Lists' section")
                    except:
                        pass  # Use all cells if filtering fails
                
                # Find cell by matching list name - use multiple strategies
                target_cell = None
                list_name_lower = list_name.lower()
                list_name_words = list_name_lower.split()[:3]  # First 3 words for matching
                stored_index = list_data.get('cell_index')
                
                # Strategy 1: Try by stored index first (if available and valid)
                # But also try nearby indices in case the list shifted
                if stored_index is not None:
                    indices_to_try = [stored_index]
                    if stored_index > 0:
                        indices_to_try.append(stored_index - 1)
                    if stored_index < len(all_cells_refresh) - 1:
                        indices_to_try.append(stored_index + 1)
                    
                    for idx in indices_to_try:
                        if 0 <= idx < len(all_cells_refresh):
                            try:
                                candidate = all_cells_refresh[idx]
                                c_text = self._get_text(candidate).strip().lower()
                                if list_name_lower in c_text or any(word in c_text for word in list_name_words if len(word) > 2):
                                    target_cell = candidate
                                    print(f"    Found cell by index {idx} (stored: {stored_index})")
                                    break
                            except:
                                continue
                
                # Strategy 2: Search by name matching
                if not target_cell:
                    for c in all_cells_refresh:
                        try:
                            c_text = self._get_text(c).strip()
                            c_text_lower = c_text.lower()
                            
                            # Exact name match
                            if list_name_lower in c_text_lower:
                                target_cell = c
                                break
                            
                            # First few words match
                            if len(list_name_words) >= 2:
                                if all(word in c_text_lower for word in list_name_words):
                                    target_cell = c
                                    break
                            
                            # Check first line of cell text
                            first_line = c_text.split('\n')[0].strip().lower() if c_text else ""
                            if list_name_lower in first_line:
                                target_cell = c
                                break
                            
                            # Partial match on first part of name
                            if len(list_name_lower) > 5:
                                name_start = list_name_lower[:min(15, len(list_name_lower))]
                                if name_start in first_line:
                                    target_cell = c
                                    break
                        except:
                            continue
                
                if not target_cell:
                    print(f"    ⚠ Could not find cell for '{list_name}' (tried index {stored_index} and name matching), skipping")
                    continue
                
                # Try to find a clickable link within the cell first (more reliable than clicking the cell)
                link_clicked = False
                try:
                    def click_link_in_cell():
                        if self.use_playwright:
                            links = target_cell.locator('a[href]').all()
                            for link in links:
                                try:
                                    href = link.get_attribute('href') or link.evaluate('el => el.href')
                                    if href and '/lists/' in href:
                                        # Scroll link into view
                                        link.scroll_into_view_if_needed()
                                        time.sleep(0.5)
                                        link.click()
                                        return True
                                except:
                                    continue
                        else:
                            links = target_cell.find_elements(By.CSS_SELECTOR, 'a[href]')
                            for link in links:
                                try:
                                    href = link.get_attribute('href')
                                    if href and '/lists/' in href:
                                        # Scroll link into view
                                        self.scraper.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link)
                                        time.sleep(0.5)
                                        link.click()
                                        return True
                                except:
                                    continue
                        return False
                    
                    # Try to click link with retry
                    try:
                        link_clicked = retry_with_exponential_backoff(
                            click_link_in_cell,
                            max_retries=2,
                            initial_wait=1.0,
                            max_wait=15.0,
                            backoff_factor=2.0
                        )
                    except:
                        pass  # If link clicking fails, fall back to cell clicking
                except:
                    pass
                
                # If no link found, click the cell itself
                if not link_clicked:
                    try:
                        def click_cell():
                            # Scroll the target cell into view before clicking
                            if self.use_playwright:
                                target_cell.scroll_into_view_if_needed()
                            else:
                                self.scraper.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", target_cell)
                            time.sleep(0.5)
                            
                            # Click the cell
                            if self.use_playwright:
                                target_cell.click()
                            else:
                                target_cell.click()
                            return True
                        
                        # Retry with exponential backoff
                        retry_with_exponential_backoff(
                            click_cell,
                            max_retries=3,
                            initial_wait=2.0,
                            max_wait=30.0,
                            backoff_factor=2.0
                        )
                    except Exception as e:
                        print(f"    ⚠ Error clicking cell after retries: {e}")
                        continue
                
                # Wait after clicking with exponential backoff consideration
                time.sleep(3)
                
                # Get URL after navigation
                new_url = self._get_current_url()
                print(f"    Navigated to: {new_url}")
                
                if '/lists/' in new_url:
                    list_url = new_url
                    match = re.search(r'/i/lists/(\d+)', new_url)
                    if match:
                        list_id = match.group(1)
                        print(f"    ✓ Extracted list_id: {list_id}")
                    else:
                        # Try slug format
                        slug_match = re.search(r'/([^/]+)/lists/([^/?]+)', new_url)
                        if slug_match:
                            list_id = slug_match.group(2)
                            print(f"    ✓ Extracted list_id (slug): {list_id}")
                    
                            # Go back to lists page with retry logic
                            def go_back_and_wait():
                                self._go_back()
                                time.sleep(3)  # Wait longer for page to reload
                                
                                # Wait for lists page to be ready
                                if self.use_playwright:
                                    self.scraper.driver.wait_for_selector('div[data-testid="listCell"]', timeout=10000)
                                else:
                                    wait = WebDriverWait(self.scraper.driver, 10)
                                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div[data-testid="listCell"]')))
                                return True
                            
                            try:
                                retry_with_exponential_backoff(
                                    go_back_and_wait,
                                    max_retries=3,
                                    initial_wait=2.0,
                                    max_wait=30.0,
                                    backoff_factor=2.0,
                                    exceptions=(TimeoutException, Exception)
                                )
                            except:
                                pass  # Continue anyway if retries fail
                else:
                    print(f"    ⚠ URL doesn't contain '/lists/', going back...")
                    if new_url != current_url:
                        self._go_back()
                        time.sleep(2)
                    list_id = None
            except Exception as e:
                import traceback
                print(f"    ⚠ Error clicking cell: {e}")
                print(f"    Traceback: {traceback.format_exc()}")
                # Try to navigate back to lists page
                try:
                    current_url = self._get_current_url()
                    if '/lists/' not in current_url:
                        username = self.twitter_profile.twitter_username
                        self._navigate_to(f"https://x.com/{username}/lists")
                        time.sleep(3)
                except:
                    pass
                list_id = None
            
            # Skip if we don't have a valid list_id
            if not list_id:
                print(f"    ⚠ Skipping '{list_name}' - no list_id extracted")
                continue
            
            # Skip duplicates
            if list_id in seen_list_ids:
                print(f"    ⚠ Skipping '{list_name}' - duplicate list_id: {list_id}")
                continue
            
            seen_list_ids.add(list_id)
            
            # Add to results
            lists.append({
                'list_id': list_id,
                'list_name': list_name,
                'list_url': list_url or f"https://x.com/i/lists/{list_id}",
                'list_slug': '',
            })
            print(f"    ✅ Added: '{list_name}' (ID: {list_id})")
        
        print(f"\n✓ Found {len(lists)} unique lists")
        return lists
    
    def sync_list(self, list_id: str, list_name: str, list_url: str = None) -> TwitterList:
        """Sync a Twitter list and create/update the database record."""
        twitter_list, created = TwitterList.objects.get_or_create(
            twitter_profile=self.twitter_profile,
            list_id=list_id,
            defaults={
                'list_name': list_name,
                'list_url': list_url or f"https://x.com/i/lists/{list_id}",
                'last_synced_at': timezone.now(),
            }
        )
        
        if not created:
            twitter_list.list_name = list_name
            if list_url:
                twitter_list.list_url = list_url
            twitter_list.last_synced_at = timezone.now()
            twitter_list.save()
        
        return twitter_list
    
    def get_list_tweets(self, twitter_list: TwitterList, max_tweets: int = 500) -> List[Dict]:
        """Fetch tweets from a specific list."""
        if not self.scraper.driver:
            if not self.scraper.login():
                raise Exception("Failed to login to Twitter")
        
        tweets = []
        seen_tweet_ids = set()
        
        list_url = twitter_list.list_url or f"https://x.com/i/lists/{twitter_list.list_id}"
        print(f"Navigating to list: {list_url}")
        
        self._navigate_to(list_url)
        time.sleep(5)
        
        # Cookie consent already handled, don't check again
        
        # Wait for tweets to load
        try:
            if self.use_playwright:
                self.scraper.driver.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
                print("List page loaded")
            else:
                WebDriverWait(self.scraper.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'article[data-testid="tweet"]'))
                )
                print("List page loaded")
        except TimeoutException:
            print("Warning: No tweets found initially, continuing anyway...")
        except Exception as e:
            print(f"Warning: Error waiting for tweets: {e}, continuing anyway...")
        
        # Scroll and collect tweets (similar to bookmarks)
        if self.use_playwright:
            last_height = self.scraper.driver.evaluate("document.body.scrollHeight")
        else:
            last_height = self.scraper.driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scrolls = 50
        no_new_tweets_count = 0
        max_no_new_tweets = 5
        
        while len(tweets) < max_tweets and scroll_attempts < max_scrolls:
            tweet_elements = self._find_elements('article[data-testid="tweet"]', By.CSS_SELECTOR)
            if self.use_playwright:
                tweet_elements = list(tweet_elements)
            print(f"Found {len(tweet_elements)} tweet elements, currently have {len(tweets)} unique tweets")
            
            new_tweets_this_scroll = 0
            for element in tweet_elements:
                try:
                    tweet_data = self.scraper._extract_tweet_data(element)
                    if tweet_data and tweet_data.get('tweet_id'):
                        tweet_id = tweet_data['tweet_id']
                        if tweet_id not in seen_tweet_ids:
                            seen_tweet_ids.add(tweet_id)
                            tweets.append(tweet_data)
                            new_tweets_this_scroll += 1
                except Exception as e:
                    print(f"Error extracting tweet: {e}")
                    continue
            
            if new_tweets_this_scroll == 0:
                no_new_tweets_count += 1
                if no_new_tweets_count >= max_no_new_tweets:
                    break
            else:
                no_new_tweets_count = 0
            
            # Scroll down
            if self.use_playwright:
                self.scraper.driver.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                self.scraper.driver.evaluate("window.scrollBy(0, 1000);")
                time.sleep(1)
                new_height = self.scraper.driver.evaluate("document.body.scrollHeight")
            else:
                self.scraper.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                self.scraper.driver.execute_script("window.scrollBy(0, 1000);")
                time.sleep(1)
                new_height = self.scraper.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
            else:
                scroll_attempts = 0
            
            last_height = new_height
        
        print(f"Finished collecting {len(tweets)} unique tweets from list")
        
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
                print(f"Found {len(tweets_needing_full_text)} list tweets with 'Show more' links, fetching full text...")
                self.scraper._fetch_full_text_batch(tweets_needing_full_text)
            except Exception as e:
                print(f"Error during full text batch fetching: {e}")
                import traceback
                traceback.print_exc()
                # Continue - truncated text will be used as fallback
        
        return tweets[:max_tweets] if max_tweets > 0 else tweets
    
    def save_list_tweets(self, twitter_list: TwitterList, tweets: List[Dict], seen_date: date = None):
        """Save tweets from a list to the database."""
        if seen_date is None:
            seen_date = timezone.now().date()
        
        saved_count = 0
        for tweet_data in tweets:
            try:
                # Get or create the Tweet
                tweet, _ = Tweet.objects.get_or_create(
                    twitter_profile=self.twitter_profile,
                    tweet_id=tweet_data['tweet_id'],
                    defaults={
                        'author_username': tweet_data.get('author_username', ''),
                        'author_display_name': tweet_data.get('author_display_name', ''),
                        'author_profile_image_url': tweet_data.get('author_profile_image_url', ''),
                        'text_content': tweet_data.get('text_content', ''),
                        'html_content': tweet_data.get('html_content', ''),
                        'created_at': tweet_data.get('created_at', timezone.now()),
                        'like_count': tweet_data.get('like_count', 0),
                        'retweet_count': tweet_data.get('retweet_count', 0),
                        'reply_count': tweet_data.get('reply_count', 0),
                        'is_bookmark': False,  # These are list tweets, not bookmarks
                        'raw_data': tweet_data,
                    }
                )
                
                # Create ListTweet association
                list_tweet, created = ListTweet.objects.get_or_create(
                    twitter_list=twitter_list,
                    tweet=tweet,
                    seen_date=seen_date,
                )
                
                if created:
                    saved_count += 1
                    
            except Exception as e:
                print(f"Error saving tweet {tweet_data.get('tweet_id')}: {e}")
                continue
        
        print(f"Saved {saved_count} new list tweets")
        return saved_count
