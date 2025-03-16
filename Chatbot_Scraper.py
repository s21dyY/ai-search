# Scraping using method from here: https://www.zenrows.com/blog/selenium-cloudflare-bypass#seleniumbase
# Selenium base API for reference: https://seleniumbase.io/help_docs/method_summary/#seleniumbase-methods-api-reference

from seleniumbase import Driver

# Base class for scraping - The ChatGPT and Perplexity Scrapers will inherit from this class
class BaseScraper:
    def __init__(self):
        # Set headless=False for debug so you can see what's happening in the browser
        self.driver = Driver(uc=True, headless=True)
        #self.driver.maximize_window()
        self.driver.set_window_size(1920, 2400)

    def __del__(self):
        if self.driver:
            self.driver.quit()

    def login(self, username, password):
        self.username = username
        self.password = password

    def query(self, query):
        return None

    def collect_data(self):
        return None

    def close(self):
        if self.driver:
            self.driver.quit()