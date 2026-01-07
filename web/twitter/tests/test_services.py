"""
Tests for TwitterScraper.
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from twitter.services import TwitterScraper


class TestTwitterScraper:
    """Tests for TwitterScraper class."""
    
    def test_twitter_scraper_initialization(self):
        """Test TwitterScraper can be initialized."""
        scraper = TwitterScraper(
            username='testuser',
            password='testpass',
            use_playwright=False
        )
        
        assert scraper.username == 'testuser'
        assert scraper.password == 'testpass'
        assert scraper.use_playwright is False
        assert scraper.driver is None
    
    def test_twitter_scraper_initialization_with_cookies(self):
        """Test TwitterScraper initialization with cookies."""
        cookies = {'session': 'abc123'}
        scraper = TwitterScraper(
            username='testuser',
            cookies=cookies,
            use_playwright=False
        )
        
        assert scraper.username == 'testuser'
        assert scraper.cookies == cookies
    
    @patch('twitter.services.webdriver.Chrome')
    @patch('twitter.services.Service')
    @patch('twitter.services.config')
    @patch('twitter.services.os.path.exists')
    @patch('twitter.services.os.access')
    def test_init_selenium_driver_success(self, mock_access, mock_exists, mock_config, mock_service_class, mock_chrome_class):
        """Test _init_selenium_driver successfully initializes driver."""
        # Setup mocks
        mock_exists.return_value = True
        mock_access.return_value = True
        mock_config.side_effect = lambda key, default, cast=None: {
            'USE_HEADLESS': 'True',
            'SELENIUM_DRIVER_PATH': '/usr/local/bin/chromedriver'
        }.get(key, default)
        
        mock_driver = MagicMock()
        mock_chrome_class.return_value = mock_driver
        
        scraper = TwitterScraper(username='testuser', use_playwright=False)
        
        scraper._init_selenium_driver()
        
        assert scraper.driver is not None
        assert mock_chrome_class.called
    
    @patch('twitter.services.config')
    @patch('twitter.services.os.path.exists')
    def test_init_selenium_driver_chromedriver_not_found(self, mock_exists, mock_config):
        """Test _init_selenium_driver raises error when ChromeDriver not found."""
        mock_exists.return_value = False
        mock_config.return_value = '/nonexistent/chromedriver'
        
        scraper = TwitterScraper(username='testuser', use_playwright=False)
        
        with pytest.raises(FileNotFoundError, match='ChromeDriver not found'):
            scraper._init_selenium_driver()
    
    @patch('playwright.sync_api.sync_playwright')
    def test_init_playwright_success(self, mock_sync_playwright):
        """Test _init_playwright successfully initializes Playwright."""
        # Setup mocks
        mock_playwright_instance = MagicMock()
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        
        # sync_playwright() returns a context manager, start() returns playwright instance
        mock_playwright_context = MagicMock()
        mock_sync_playwright.return_value = mock_playwright_context
        mock_playwright_context.__enter__.return_value.start.return_value = mock_playwright_instance
        mock_playwright_instance.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        
        scraper = TwitterScraper(username='testuser', use_playwright=True)
        
        scraper._init_playwright_driver()
        
        assert scraper.playwright is not None
        assert scraper.browser is not None
        assert scraper.context is not None
        assert scraper.driver is not None
    
    @patch('playwright.sync_api.sync_playwright')
    def test_init_playwright_error(self, mock_sync_playwright):
        """Test _init_playwright handles errors gracefully."""
        mock_sync_playwright.side_effect = Exception('Playwright error')
        
        scraper = TwitterScraper(username='testuser', use_playwright=True)
        
        with pytest.raises(Exception):
            scraper._init_playwright_driver()
    
    @patch('twitter.services.TwitterScraper._init_selenium_driver')
    def test_login_with_password_success(self, mock_init_driver):
        """Test login successfully logs in with password."""
        mock_driver = MagicMock()
        mock_driver.current_url = 'https://x.com/home'
        mock_driver.find_elements.return_value = []
        mock_init_driver.return_value = None
        
        scraper = TwitterScraper(username='testuser', password='testpass', use_playwright=False)
        scraper.driver = mock_driver
        
        # Mock navigation and element finding
        with patch.object(scraper.driver, 'get') as mock_get, \
             patch('twitter.services.WebDriverWait') as mock_wait, \
             patch('twitter.services.EC') as mock_ec:
            mock_wait.return_value.until.return_value = MagicMock()
            
            result = scraper.login()
            
            # Should attempt login
            assert mock_get.called
    
    @patch('twitter.services.TwitterScraper._init_selenium_driver')
    def test_login_with_cookies_success(self, mock_init_driver):
        """Test login successfully logs in with cookies."""
        mock_driver = MagicMock()
        mock_driver.current_url = 'https://x.com/home'
        mock_init_driver.return_value = None
        
        cookies = {'session': 'abc123'}
        scraper = TwitterScraper(username='testuser', cookies=cookies, use_playwright=False)
        scraper.driver = mock_driver
        
        with patch.object(scraper.driver, 'get') as mock_get:
            result = scraper.login()
            
            # Should navigate to Twitter
            assert mock_get.called
    
    @patch('twitter.services.TwitterScraper._init_selenium_driver')
    def test_get_bookmarks_success(self, mock_init_driver):
        """Test get_bookmarks successfully fetches bookmarks."""
        mock_driver = MagicMock()
        mock_driver.current_url = 'https://x.com/i/bookmarks'
        mock_driver.find_elements.return_value = []
        mock_init_driver.return_value = None
        
        scraper = TwitterScraper(username='testuser', cookies={'session': 'abc'}, use_playwright=False)
        scraper.driver = mock_driver
        scraper.session_cookies = {'session': 'abc'}
        
        # Mock _execute_js to return numeric values
        def mock_execute_js(script):
            if 'scrollHeight' in script:
                return 1000
            elif 'pageYOffset' in script or 'innerHeight' in script:
                return 500
            return 0
        
        with patch.object(scraper.driver, 'get') as mock_get, \
             patch('twitter.services.WebDriverWait') as mock_wait, \
             patch('twitter.services.EC') as mock_ec, \
             patch('twitter.services.time.sleep'), \
             patch.object(scraper, '_execute_js', side_effect=mock_execute_js):
            mock_wait.return_value.until.return_value = MagicMock()
            
            bookmarks = scraper.get_bookmarks(max_bookmarks=10)
            
            # Should return list (may be empty if no bookmarks found)
            assert isinstance(bookmarks, list)
    
    @patch('twitter.services.TwitterScraper._init_selenium_driver')
    def test_get_bookmarks_not_logged_in(self, mock_init_driver):
        """Test get_bookmarks handles not logged in state."""
        mock_driver = MagicMock()
        mock_driver.current_url = 'https://x.com/i/flow/login'
        mock_init_driver.return_value = None
        
        scraper = TwitterScraper(username='testuser', cookies={'session': 'abc'}, use_playwright=False)
        scraper.driver = mock_driver
        
        # Mock _execute_js to return numeric values
        def mock_execute_js(script):
            if 'scrollHeight' in script:
                return 1000
            elif 'pageYOffset' in script or 'innerHeight' in script:
                return 500
            return 0
        
        with patch.object(scraper, 'login', return_value=False), \
             patch.object(scraper, '_execute_js', side_effect=mock_execute_js):
            bookmarks = scraper.get_bookmarks(max_bookmarks=10)
            
            # Should return empty list or handle gracefully
            assert isinstance(bookmarks, list)
    
    def test_close_selenium(self):
        """Test close cleans up Selenium driver."""
        mock_driver = MagicMock()
        
        scraper = TwitterScraper(username='testuser', use_playwright=False)
        scraper.driver = mock_driver
        
        scraper.close()
        
        mock_driver.quit.assert_called_once()
        assert scraper.driver is None
    
    def test_close_playwright(self):
        """Test close cleans up Playwright browser."""
        mock_browser = MagicMock()
        mock_context = MagicMock()
        
        scraper = TwitterScraper(username='testuser', use_playwright=True)
        scraper.browser = mock_browser
        scraper.context = mock_context
        scraper.playwright = MagicMock()
        
        scraper.close()
        
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        assert scraper.browser is None
        assert scraper.context is None

