"""
Helper functions to make Playwright locators work like Selenium elements.
This allows _extract_tweet_data to work with both without major refactoring.
"""
from selenium.webdriver.common.by import By

class PlaywrightElementWrapper:
    """Wraps Playwright Locator to behave like Selenium WebElement."""
    
    def __init__(self, locator):
        self.locator = locator
    
    def find_element(self, by, value):
        """Find a single element - converts Selenium By to Playwright selector."""
        if by == 'css selector':
            new_locator = self.locator.locator(value).first
            return PlaywrightElementWrapper(new_locator)
        elif by == 'xpath':
            new_locator = self.locator.locator(f'xpath={value}').first
            return PlaywrightElementWrapper(new_locator)
        else:
            raise ValueError(f"Unsupported selector type: {by}")
    
    def find_elements(self, by, value):
        """Find multiple elements."""
        if isinstance(by, str):
            if by == 'css selector' or by == By.CSS_SELECTOR:
                locators = self.locator.locator(value).all()
                return [PlaywrightElementWrapper(loc) for loc in locators]
            elif by == 'xpath' or by == By.XPATH:
                locators = self.locator.locator(f'xpath={value}').all()
                return [PlaywrightElementWrapper(loc) for loc in locators]
        else:
            if by == By.CSS_SELECTOR:
                locators = self.locator.locator(value).all()
                return [PlaywrightElementWrapper(loc) for loc in locators]
            elif by == By.XPATH:
                locators = self.locator.locator(f'xpath={value}').all()
                return [PlaywrightElementWrapper(loc) for loc in locators]
        
        raise ValueError(f"Unsupported selector type: {by}")
    
    def get_attribute(self, name):
        """Get attribute value."""
        try:
            return self.locator.get_attribute(name) or ''
        except:
            return ''
    
    @property
    def text(self):
        """Get element text."""
        try:
            return self.locator.text_content() or ''
        except:
            return ''
    
    @property
    def size(self):
        """Get element size (for compatibility with Selenium)."""
        try:
            box = self.locator.bounding_box()
            if box:
                return {'width': int(box['width']), 'height': int(box['height'])}
            return {'width': 0, 'height': 0}
        except:
            return {'width': 0, 'height': 0}
    
    def __getattr__(self, name):
        """Forward any other attributes to the locator."""
        return getattr(self.locator, name)

