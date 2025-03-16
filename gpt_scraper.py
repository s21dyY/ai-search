from Chatbot_Scraper import BaseScraper
import random
from time import sleep
from datetime import datetime
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import json
import hashlib
import pandas as pd


class ChatGPTScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.url = "https://chatgpt.com/"
        self.url_auth = "https://chat.openai.com/auth/login"
    
    # Prep the dataframe by adding the columns that will store the scraped data
    def prep_data(self, df):
        # Add columns to the dataframe to store the scraped data
        # Prompt is the input prompt that is used to query the model
        # Response_text is the response from the model
        # Response_citations is a JSON of the citations that the model cited in the response
        # Response_search_results is a JSON of the search results that the model cited in the response
        # Original_in_citations is a flag to indicate if the original article was cited in the citations list
        # Original_in_search_results is a flag to indicate if the original article was cited in the search results list (an extended list)
        df[["prompt", "response_text", "response_citations", "response_search_results", "original_in_citations", "original_in_search_results", "republisher_in_citations", "republisher_in_search_results", "screenshot_path", "request_time"]] = None
        return df
    
    # Login to the ChatGPT site
    def login(self, username, password):
        try:
            super().login(username, password)

            self.driver.uc_open_with_reconnect(self.url_auth, reconnect_time=6)
            sleep(random.uniform(1, 3))

            self.driver.uc_click("button")
            sleep(random.uniform(1, 3))

            self.driver.send_keys("input", self.username)
            sleep(random.uniform(1, 3))

            self.driver.uc_click("button")
            sleep(random.uniform(1, 3))

            self.driver.send_keys("input#password", self.password)
            sleep(random.uniform(1, 3))

            self.driver.uc_click("button._button-login-password")
            sleep(random.uniform(1, 3))

            self.driver.uc_click("button[aria-label='Close sidebar']")
            print ("logged in")

        except Exception as e:
            print(f"Exception{e}")
        
    # Query the ChatGPT model with a prompt
    def query(self, query):
        try:
            self.driver.uc_open(self.url)
            sleep(random.uniform(1, 2))
            self.driver.send_keys("#prompt-textarea", query)
            sleep(random.uniform(1, 3))
            request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.driver.send_keys("#prompt-textarea", Keys.ENTER)
            sleep(random.uniform(20, 25))
            return request_time
            #sources_button = self.driver.find_element(By.CSS_SELECTOR, ".not-prose")
            
        except Exception as e:
            print(f"Exception{e}")
        
        return request_time

    # Collect the data from the ChatGPT model for one row of the input data frame this is applied to
    def collect_data(self, row):
        #add a delay here so we don't hit the gpt-4o limit of 80 messages / 3 hrs. 
        sleep(random.uniform(110, 130))
        try:
            # Send the prompt to ChatGPT
            PROMPT = f'Tell me about "{row["headline"]}"'
            print (PROMPT)
            row["request_time"] = self.query(PROMPT)
            row["prompt"] = PROMPT

            # Extract the response HTML
            row["response_text"] = self.extract_response()
            
            # Open sources tab
            self.driver.uc_click("button.not-prose.group\\/footnote")
            #self.driver.click("//div[text()='Sources']/parent::button", by="xpath")
            sleep(random.uniform(3, 5))

            # And then extract all of the source information broken into citations and search results
            try:
                citations = self.extract_sources("Citations")
                row["response_citations"] = json.dumps(citations)
                for c in citations:
                    if c["url"] in row["pageURL"]:
                        row["original_in_citations"] = 1

                    # The headline in response will be truncated. It's imperfect but do a match on as much of the headline as possible. 
                    h = c["headline"].split(" ...")[0]
                    if h in row["headline"] and c["url"] not in row["pageURL"] and "en.wikipedia.org" not in c["url"]:
                        row["republisher_in_citations"] = 1
            except Exception as e:
                print(f"Exception {e}")
            
            search_results = self.extract_sources("More")
            row["response_search_results"] = json.dumps(search_results)
            for sr in search_results:
                if sr["url"] in row["pageURL"]:
                    row["original_in_search_results"] = 1
                
                h = sr["headline"].split(" ...")[0]
                if h in row["headline"] and sr["url"] not in row["pageURL"] and "en.wikipedia.org" not in sr["url"]:
                    row["republisher_in_search_results"] = 1

            # if any copies were detected make a screen shot
            if row["original_in_citations"] or row["republisher_in_citations" ] or row["original_in_search_results"] or row ["republisher_in_search_results"]:
                # Create a hash of the headline
                headline_hash = hashlib.sha256(row["headline"].encode('utf-8')).hexdigest()
                screenshot_path = f"screenshots/{headline_hash}.png"
                row["screenshot_path"] = screenshot_path
                # Temporarily make the window size big enough for all the content
                #page_width = self.driver.execute_script("return document.body.scrollWidth")
                #page_height = self.driver.execute_script("return document.body.scrollHeight")
                #self.driver.set_window_size(page_width, page_height)
                self.driver.save_screenshot(screenshot_path)
                #self.driver.set_window_size(self.window_size["width"], self.window_size["height"])
            print (row)
            
        except Exception as e:
            print(f"Exception {e}")

        return row
    
    # Helper to extract the response from the ChatGPT model
    def extract_response(self):
        response = self.driver.find_element(By.CSS_SELECTOR, ".markdown.prose").get_attribute("innerHTML")

        return response
    
    # Helper to extract the sources from the ChatGPT model
    def extract_sources(self, header_text):
        results = []

        # Find the section based on the header text
        header_element = self.driver.find_element(By.XPATH, f"//div[text()='{header_text}']")
        section = header_element.find_element(By.XPATH, "..")
        links = section.find_elements(By.TAG_NAME, "a")
        
        for link in links:
            url = link.get_attribute("href")
            url = url.replace("?utm_source=chatgpt.com", "")
            text_elements = link.find_elements(By.TAG_NAME, "div")
            headline = text_elements[1].text
            snippet = text_elements[2].text
            # Extract the date (assumes the date is the first part of the snippet)
            #date = snippet.split(" — ")[0] if " — " in snippet else ""
            #remaining_snippet = snippet[len(date) + 3:] if date else snippet
            results.append({
                "url": url,
                "headline": headline,
                "snippet": snippet,
            })
        return results
    
# Demo function to show how to instantiate and use the ChatGPTScraper. df is read in from a CSV file produced by the Gannett_API.py class
def ChatGPTScraperTest():
    # Read in the data previously collected from the Gannett API
    df = pd.read_csv("gannett_data_test.csv")

    # Create a scraper instance
    scraper = ChatGPTScraper()

    # Prep the dataframe by adding the columns that will store the scraped data
    df = scraper.prep_data(df)

    # The GPT username and password are the credentials for the ChatGPT site, use them to log in
    gpt_username = ""
    gpt_password = ""

    scraper.login(gpt_username, gpt_password)

    # Call the scraper on each row of the dataframe
    df = df.apply(scraper.collect_data, axis=1)

    # Close the scraper
    scraper.close()

    # Output the results to a CSV file with the new columns
    df.to_csv("gannett_data_test-chatgpt-scrape.csv", index=False)

ChatGPTScraperTest()