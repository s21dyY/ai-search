from Chatbot_Scraper import BaseScraper
import random
from time import sleep
from datetime import datetime
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import json
import hashlib
import pandas as pd
import poplib
from email import parser
from newspaper import Article
import requests

class PerplexityScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.url = "https://www.perplexity.ai"
        self.url_auth = "https://www.perplexity.ai"
        # Subsitute your own email pop server here
        self.pop = "pop.ionos.com"

    # Prep the dataframe by adding the columns that will store the scraped data
    def prep_data(self, df):
        # Prompt is the prompt that was used the query the model
        # Response text is the response from the model
        # Response sources is as JSON of the sources that the model cited in the response
        # Original in sources is a flag to indicate if the original article was cited in the sources list
        # Original cited in answer is a flag to indicate if the original article was cited in the response itself since sometimes a source is in the sources list but not the actual response
        # Republisher in sources is a flag to indicate if a republisher was cited in the sources list (e.g. Yahoo, AOL), based on a headline match
        # Republisher cited in answer is a flag to indicate if a republisher was cited in the response itself
        df[["prompt", "response_text", "response_sources", "original_in_sources", "original_cited_in_answer", "republisher_in_sources", "republisher_cited_in_answer", "screenshot_path", "request_time"]] = None
        return df
     
    # Login to the Perplexity site - this is a bit more complex because it requires an email verification code
    def login(self, perplexity_username, email_username, email_password):
        try:
            super().login(perplexity_username, "")
            self.driver.uc_open_with_reconnect(self.url_auth, reconnect_time=6)
            sleep(random.uniform(1, 3))

            self.driver.send_keys("input[type='email']", self.username)
            sleep(random.uniform(1, 3))

            self.driver.send_keys("input[type='email']", Keys.ENTER)
            sleep(random.uniform(8, 10))

            # Grab the last email in the inbox which should have the code 
            pop_conn = poplib.POP3_SSL(self.pop)
            pop_conn.user(email_username)
            pop_conn.pass_(email_password)
            num_messages = len(pop_conn.list()[1])
            verification_code = ""
            for i in range(num_messages, num_messages+1):  # Emails are 1-indexed
                response, lines, octets = pop_conn.retr(i)  # Fetch the email
                
                # Decode the message content
                raw_message = b"\n".join(lines).decode(errors="ignore")
                email_message = parser.Parser().parsestr(raw_message)

                # Extract the body (plain text)
                body = ""
                if email_message.is_multipart():
                    for part in email_message.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            body = part.get_payload(decode=True).decode(errors="ignore")
                            break
                else:
                    body = email_message.get_payload(decode=True).decode(errors="ignore")

                search_string = "If the link does not work, you can use the login verification code directly:"

                # Find the starting index of the search string
                index = body.find(search_string)

                # Ensure the substring was found
                if index != -1:
                    # Calculate the position where the code starts (end of search_string)
                    code_start = index + len(search_string)

                    # Extract the next 11 characters as the verification code
                    verification_code = body[code_start+2:code_start + 13]
                
                print ("code:", verification_code)

            self.driver.uc_click("button")
            sleep(random.uniform(1, 3))

            self.driver.send_keys("input", verification_code)

            print ("logged in")
            sleep(random.uniform(3, 5))

        except Exception as e:
            print(f"Exception{e}")
        
    # Query the Perplexity model with a prompt
    def query(self, query):
        try:
            self.driver.uc_open(self.url)
            sleep(random.uniform(1, 2))
            self.driver.send_keys("textarea", query)
            sleep(random.uniform(1, 3))
            request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.driver.send_keys("textarea", Keys.ENTER)
            sleep(random.uniform(25, 30))
            return request_time
        except Exception as e:
            print(f"Exception{e}")
            
    # query the model and extract the response and sources for one row of an input data frame at a time
    def collect_data(self, row):
        sleep(random.uniform(60, 65))
        try:
            # Send the prompt to ChatGPT - ??
            PROMPT = f'Tell me about "{row["headline"]}"'
            print (PROMPT)
            row["request_time"] = self.query(PROMPT)
            row["prompt"] = PROMPT

            # Extract the response HTML
            row["response_text"] = self.driver.find_element(By.CSS_SELECTOR, ".prose").get_attribute("innerHTML")
            
            # Open sources tab
            #self.driver.save_screenshot("debug.png")
            #show_all_sources = self.driver.find_element(By.XPATH, f"//div[text()='Show all']")
            #print (show_all_sources)
            self.driver.click("//div[text()='Show all']", by=By.XPATH)
            #self.driver.click("//div[text()='Sources']/parent::button", by="xpath")
            sleep(random.uniform(3, 5))
            #self.driver.save_screenshot("debug-2.png")

            sources_links_answer = self.driver.find_elements(By.CSS_SELECTOR, ".prose * a")
            sources_cited_in_answer = []
            for s in sources_links_answer:
                url = s.get_attribute("href")
                sources_cited_in_answer.append(url)

            # get sources in sidebar
            sources = []
            sources_links = self.driver.find_elements(By.CSS_SELECTOR, ".isolate.col-span-4 * a")
            for sl in sources_links:
                url = sl.get_attribute("href")
                sle = sl.find_elements(By.CSS_SELECTOR, ".items > div")
                headline = sle[0].text
                snippet = ""
                if len(sle) == 3:
                    snippet = sle[2].text
                
                # Grab the article headline from the url to be able to match it to the original headline and see if there are any republications
                print ("  Requesting: ", url)
                article = Article(url)
                try:
                    r = requests.request("GET", url, timeout = (8, 8))
                    article.download(input_html = r.text)
                    article.parse()
                except Exception as e:
                    print(f"Exception {e}")
                    continue
                
                # Check if the source is cited in the answer
                cited_in_answer = 0
                if url in sources_cited_in_answer:
                    cited_in_answer = 1

                sources.append({
                    "url": url,
                    "headline": headline,
                    "snippet": snippet,
                    "retrieved_headline": article.title,
                    "cited_in_answer": cited_in_answer,
                })
            #print (sources)
            row["response_sources"] = json.dumps(sources)
            
            # Set the flags for original and republisher based on the sources
            for s in sources:
                if s["url"] == row["pageURL"]:
                    row["original_in_sources"] = 1
                    if s["cited_in_answer"] == 1:
                        row["original_cited_in_answer"] = 1
                else:
                    if s["retrieved_headline"] != "" and s["retrieved_headline"] == row["headline"]:
                        row["republisher_in_sources"] = 1
                        if s["cited_in_answer"] == 1:
                            row["republisher_cited_in_answer"] = 1

            # if any flags were detected make a screen shot
            if row["original_in_sources"] or row["republisher_in_sources" ]:
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

        except Exception as e:
            print(f"Exception {e}")

        return row

# Demo function to show how to instantiate and use the PerplexityScraper. df is read in from a CSV file produced by the Gannett_API.py class
def PerplexityScraperTest():
    # Read in the data previously collected from the Gannett API
    df = pd.read_csv("gannett_data_test.csv")

    # Create a scraper instance
    scraper = PerplexityScraper()

    # Prep the dataframe by adding the columns that will store the scraped data
    df = scraper.prep_data(df)

    # The perplexity username is the account email address
    # email_username and email_password are the credentials for the email account that will receive the verification code (separate so that one can forward to the other)
    perplexity_username = ""
    email_username = ""
    email_password = ""

    # Login if you want to test the latest models, however ifnot logged in you can still test it with their "auto" model
    scraper.login(perplexity_username, email_username, email_password)

    # Call the scraper on each row of the dataframe
    df = df.apply(scraper.collect_data, axis=1)

    # Close the scraper
    scraper.close()

    # Output the results to a CSV file with the new columns
    df.to_csv("gannett_data_test-perplexity-scrape.csv", index=False)

#PerplexityScraperTest()