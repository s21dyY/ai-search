# Scraping using method from here: https://www.zenrows.com/blog/selenium-cloudflare-bypass#seleniumbase
# Selenium base API for reference: https://seleniumbase.io/help_docs/method_summary/#seleniumbase-methods-api-reference

from seleniumbase import Driver
import pandas as pd
import keyring
import Set_Password
import os
from Gannett_API import GannettAPI


# Base class for scraping
# The ChatGPT and Perplexity Scrapers will inherit from this class
# includes functionality that both scrapers use
class BaseScraper:
    def __init__(self):
        # Set headless=False for debug and remove the --headless=new option so you can see what's happening in the browser
        self.driver = Driver(uc=True, headless=True, chromium_arg=[
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ])

        self.driver.set_window_size(1920, 2400)
        self.driver.set_page_load_timeout(30)

    def __del__(self):
        try:
            if hasattr(self, "driver") and self.driver:
                self.driver.quit()
        except Exception:
            pass
    
    def _login(self, username, password):
        self.username = username
        self.password = password

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None

    # logic for getting the API data
    @staticmethod
    def get_API_data(dates: str, service: str):
        
        # df = GannettAPI().test_api(dates)
        # use the line below instead of the one above to read from a .csv rather than directly pulling from the API with the given date
        df = pd.read_csv(f"gannett_API_data_{dates}.csv")
        
        os.makedirs(f'{os.getcwd()}/screenshots_{service}_{dates}/Errors', exist_ok=True)
        
        num_rows = len(df)
        print(f"Collected API data for {dates}. Scraping on {num_rows} articles...")

        return df, num_rows

    # logic for getting the password securely with an email
    @staticmethod
    def get_login_creds(service: str):
        # hardcode your username/email here so you won't be asked each time a scraper runs
        email = "lifeispoetry1@gmail.com"

        # as for a username/email if there isn't one hardcoded
        while email == "":
            email = input(f"What is you username/email for {service}?: ")
        
        # securely extract the password
        pwd = keyring.get_password(f"{service.lower()}", email)
        # if there is no password saved, run Set_Password.py
        if pwd is None:
            print(f"No password for {service} found. Running Set_Password.py...")
            # have the user set their password and save the username they input through Set_Password.py
            email = Set_Password.create_pwd(email, f"{service.lower()}")
            pwd = keyring.get_password(f"{service.lower()}", email)
    
        return email, pwd

    # Removes emojis from the given text
    @staticmethod
    def remove_non_bmp(text):
        return ''.join(c for c in text if ord(c) <= 0xFFFF)