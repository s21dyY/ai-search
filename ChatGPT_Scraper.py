from Chatbot_Scraper import BaseScraper
import random
from time import sleep
from datetime import datetime
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import sys

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

    # Login to the ChatGPT site using CMU auth
    def _login(self, usern, pwd, dates):
        try:
            super()._login(username = usern, password = pwd) # type: ignore

            self.driver.uc_open_with_reconnect(self.url_auth, reconnect_time=4)
            sleep(random.uniform(1, 3))

            #Main page for chatgpt. Clicks on "login" button
            self.driver.uc_click("button") 
            sleep(random.uniform(1, 3))
            
            #Google Sign on Button
            self.driver.uc_click("button[value='google']")
            sleep(random.uniform(1, 3))

            #Inputs username into the email box
            self.driver.send_keys("input#identifierId.whsOnd.zHQkBf", self.username) 
            sleep(random.uniform(1, 3))

            #Next Button on Google Sign in Page
            self.driver.uc_click("button.VfPpkd-LgbsSe.VfPpkd-LgbsSe-OWXEXe-k8QpJ.VfPpkd-LgbsSe-OWXEXe-dgl2Hf.nCP5yc.AjY5Oe.DuMIQc.LQeN7.BqKGqe.Jskylb.TrZEUc.lw1w4b") 
            sleep(random.uniform(1, 3))

            # Inputs password into the password box
            self.driver.send_keys("input[name='Passwd']", self.password)
            sleep(random.uniform(1, 3))

            # Next Button on Google Sign in Page
            self.driver.uc_click("#passwordNext")
            sleep(random.uniform(1, 3))


            # #CMU Andrew login username input
            # self.driver.send_keys("input#username", self.username)
            # sleep(random.uniform(1, 3))

            # #CMU Andrew login password input
            # self.driver.send_keys("input#passwordinput", self.password)
            # sleep(random.uniform(1, 3))

            # #CMU Andrew login login button
            # self.driver.uc_click("input.loginbutton")

            # #CMU DUO Push "My Device" button
            # self.driver.uc_click("button#trust-browser-button.button--primary--full-width.button--primary.button--xlarge.size-margin-top-xlarge.size-margin-bottom-medium")
            
            print("Logged into ChatGPT")

        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_gpt_{dates}/_Login_Error.png")
            print(f"Exception{e}")
        
    # Query the ChatGPT model with a prompt
    def _query_chatgpt(self, query, row_num, dates):
        try:
            self.driver.uc_open(self.url)
            sleep(random.uniform(1, 2))
            # Delete what was in the input box
            textarea = self.driver.find_element("div#prompt-textarea.ProseMirror  ") #Rename with ChatGPT textbox element name
            textarea.send_keys(Keys.CONTROL, "a")
            textarea.send_keys(Keys.BACKSPACE)

            self.driver.send_keys("div#prompt-textarea.ProseMirror  ", BaseScraper.remove_non_bmp(query)) # type: ignore
            sleep(random.uniform(1, 3))
            request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.driver.send_keys("#prompt-textarea", Keys.ENTER)
            sleep(random.uniform(20, 25))
            return request_time
            #sources_button = self.driver.find_element(By.CSS_SELECTOR, ".not-prose")
            
        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_gpt_{dates}/Errors/Article_{row_num}_Query_Error.png")
            print(f"Exception{e}")
        
    # Collect the data from the ChatGPT model for one row of the input data frame this is applied to
    def _collect_data(self, row, row_num, dates):
        # added a delay here so we don't hit the gpt-4o limit of 80 messages / 3 hrs. 
        sleep(random.uniform(20, 30))
        try:
            # Send the prompt to ChatGPT
            PROMPT = f'Tell me about "{row["headline"]}"'
            row["request_time"] = self._query_chatgpt(PROMPT, row_num, dates)
            row["prompt"] = PROMPT

            # Extract the response HTML
            row["response_text"] = self._extract_response()
            
            # Open sources tab
            # self.driver.uc_click("button.not-prose.group\\/footnote")
            self.driver.uc_click("button.group\\/footnote")
            sleep(random.uniform(3, 5))

            # And then extract all of the source information broken into citations and search results
            try:
                citations = self._extract_sources("Citations")
                row["response_citations"] = json.dumps(citations)
                for c in citations:
                    if c["url"] in row["pageURL"]:
                        row["original_in_citations"] = 1

                    # The headline in response will be truncated. It's imperfect but do a match on as much of the headline as possible. 
                    h = c["headline"].split(" ...")[0]
                    if h in row["headline"] and c["url"] not in row["pageURL"] and "en.wikipedia.org" not in c["url"]:
                        row["republisher_in_citations"] = 1

                search_results = self._extract_sources("More")
                row["response_search_results"] = json.dumps(search_results)
                for sr in search_results:
                    if sr["url"] in row["pageURL"]:
                        row["original_in_search_results"] = 1
                    
                    h = sr["headline"].split(" ...")[0]
                    if h in row["headline"] and sr["url"] not in row["pageURL"] and "en.wikipedia.org" not in sr["url"]:
                        row["republisher_in_search_results"] = 1

            except Exception as e:
                WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
                self.driver.save_screenshot(f"screenshots_gpt_{dates}/Errors/Article_{row_num}_Collecting_Sources_Error.png")
                print(f"Exception{e}")

            # if any copies were detected make a screen shot
            if row["original_in_citations"] or row["republisher_in_citations" ] or row["original_in_search_results"] or row ["republisher_in_search_results"]:
                screenshot_path = f"screenshots_gpt_{dates}/Article_{row_num}_SourceUsed.png"
                row["screenshot_path"] = screenshot_path
                self.driver.save_screenshot(screenshot_path)    

        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_gpt_{dates}/Errors/Article_{row_num}_Collect_Error.png")
            print(f"Exception{e}")

        return row
    
    # Helper to extract the response from the ChatGPT model
    def _extract_response(self):
        response = self.driver.find_element(By.CSS_SELECTOR, ".markdown.prose").get_attribute("innerHTML")

        return response
    
    # Helper to extract the sources from the ChatGPT model
    def _extract_sources(self, header_text):
        results = []

        # Find the section based on the header text
        header_element = self.driver.find_element(By.XPATH, f"//li[text()='{header_text}']")
        section = header_element.find_element(By.XPATH, "..")
        links = section.find_elements(By.TAG_NAME, "a")
        
        for link in links:
            url = link.get_attribute("href")
            url = url.replace("?utm_source=chatgpt.com", "")
            text_elements = link.find_elements(By.TAG_NAME, "div")
            headline = text_elements[1].text

            # some sources may not have snippets
            try:
                snippet = text_elements[2].text
            except:
                snippet = ""
            
            # Extract the date (assumes the date is the first part of the snippet)
            #date = snippet.split(" — ")[0] if " — " in snippet else ""
            #remaining_snippet = snippet[len(date) + 3:] if date else snippet
            results.append({
                "url": url,
                "headline": headline,
                "snippet": snippet,
            })
        return results
  
def RunChatGPTScraper():
    try:
        scraper = None
        df = None
        
        # Collect from the Gannett API: expected format is YYYY-MM-DD or YYYY-MM-DD_DD for multiple days
        try:
            dates = sys.argv[1]
        except:
            print("Need a date parameter after the filename in the form of YYYY-MM-DD or YYYY-MM-DD_DD for multiple days")
            sys.exit(1)
        
        df, num_rows = BaseScraper.get_API_data(dates, "gpt") # type: ignore

        email, pwd = BaseScraper.get_login_creds("chatgpt") # type: ignore

        # Create a scraper instance
        scraper = ChatGPTScraper()

        # Prep the dataframe by adding the columns that will store the scraped data
        df = scraper.prep_data(df)

        scraper._login(email, pwd, dates)

        # Call the scraper on each row of the dataframe
        current_row = 1
        for idx, row in df.iterrows():
            df.loc[idx] = scraper._collect_data(row, current_row, dates)
            print(f"Finished article {current_row} of {num_rows}. {round(float(current_row/num_rows) * 100, 1)} percent completed.")
        
            # Saves csv after every 50 article headlines 
            if current_row % 50 == 0:
                df.to_csv(f"gannett_gpt_{dates}.csv", index=False)
                print(f"Progress snapshot saved to 'gannett_gpt_{dates}.csv'.")

            current_row += 1

    # Catch any unhandled errors or user interrupts
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught. Saving progress...")

    except Exception as e:
        print(f"\nEncountered the following error:\n{str(e)}\n\nSaving progress...")

    # clean up and save
    finally:
        if scraper:
            scraper.close()
        
        if df is not None:
            df.to_csv(f"gannett_gpt_{dates}.csv", index=False)
            print(f"'gannett_gpt_{dates}.csv' saved successfully.")

if __name__ == "__main__":
    RunChatGPTScraper()