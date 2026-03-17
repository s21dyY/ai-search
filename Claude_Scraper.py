from pathlib import Path
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

class ClaudeScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.url = "https://claude.ai/new"
        self.url_auth = "https://claude.ai/login"
    
    # Prep the dataframe by adding the columns that will store the scraped data
    def prep_data(self, df):
        # Add columns to the dataframe to store the scraped data
        # Prompt is the input prompt that is used to query the model
        # Response is the cleaned HTML response from the model which may include tags that indicate ahrefs for citations
        # Response_text is the cleaned response from the model
        # Response_sources is a JSON of the sources that the model included in "searched the web" box 
        # Response_citations is a JSON list of  of the urls that the model cited in the response
        df[["prompt", "response", "response_text", "response_sources", "response_citations", "original_in_citations","screenshot_path", "request_time"]] = None
        return df

    # Login to the ChatGPT site using CMU auth
    def _login(self, usern, pwd, dates):
        try:
            super()._login(username = usern, password = pwd) # type: ignore

            self.driver.uc_open_with_reconnect(self.url_auth, reconnect_time=4)
            sleep(random.uniform(3, 5))

            # Sometimes an extra button we need to click to stay on the web
            if self.driver.is_element_visible('[data-testid="continue-on-web"]'):
                print ("Clicking 'Continue on web' button...")
                self.driver.uc_click('[data-testid="continue-on-web"]')
                sleep(random.uniform(3, 5))


            self.driver.uc_click('[data-testid="login-with-google"]')
            sleep(random.uniform(5, 7))
            #self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_1.png")
            
            # Force the switch to the popup login window
            #print(f"Number of open windows: {len(self.driver.window_handles)}")
            #print ('Window handles:', self.driver.window_handles)
            WebDriverWait(self.driver, 10).until(EC.number_of_windows_to_be(2))
            self.driver.switch_to_window(-1)
            #print("Currently looking at:", self.driver.get_current_url())
            self.driver.type('input[type="email"]', self.username)
            sleep(random.uniform(5, 7)) 
            #self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_2.png")

            #Next Button on Google Sign in Page
            self.driver.switch_to_window(-1)
            self.driver.uc_click("#identifierNext div button")
            sleep(random.uniform(3, 5))
            #self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_3.png")

            # Inputs password into the password box
            self.driver.switch_to_window(-1)
            self.driver.type("input[name='Passwd']", self.password)
            sleep(random.uniform(3, 5))
            #self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_4.png")

            # Next Button on Google Sign in Page
            self.driver.switch_to_window(-1)
            self.driver.uc_click("#passwordNext")
            sleep(random.uniform(3, 5))
            #self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_5.png")

            # Force back to popup
            self.driver.switch_to_window(-1)
            #print("Currently looking at:", self.driver.get_current_url())
            # Continue button 
            buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button')  
            buttons[1].click()
            sleep(random.uniform(3, 5))
            #self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_6.png")
            
            print("Logged into Claude")

        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_claude_{dates}/_Login_Error.png")
            print(f"Exception{e}")
        
    # Query the Claude model with a prompt
    def _query_claude(self, query, row_num, dates):
        try:
            self.driver.uc_open(self.url)
            sleep(random.uniform(1, 3))
            # Load it a 2nd time -- this typically refreshes any popovers. 
            self.driver.uc_open(self.url)
            sleep(random.uniform(1, 3))
            # Delete what was in the input box
            textarea = self.driver.find_element('[data-testid="chat-input"]') 
            textarea.send_keys(Keys.CONTROL, "a")
            textarea.send_keys(Keys.BACKSPACE)

            self.driver.send_keys('[data-testid="chat-input"]', BaseScraper.remove_non_bmp(query)) # type: ignore
            sleep(random.uniform(1, 3))
            request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.driver.send_keys('[data-testid="chat-input"]', Keys.ENTER)
            # Give it ~30 seconds to respond - technically it's not guaranteed to finish in this timeframe, but it's likely that it will
            sleep(random.uniform(30, 35))
            return request_time
            
        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_claude_{dates}/Errors/Article_{row_num}_Query_Error.png")
            print(f"Exception{e}")
        
    # Collect the data from the Claude model for one row of the input data frame this is applied to
    def _collect_data(self, row, row_num, dates):
        # added a delay here to avoid hitting rate limits
        try:
            # Send the prompt to Claude
            PROMPT = f'Tell me about "{row["headline"]}"'
            row["request_time"] = self._query_claude(PROMPT, row_num, dates)
            row["prompt"] = PROMPT

            # Extract the response and text (stick it right in our output dataframe)
            self._extract_response(row)
            
            try:
                # Open sources tab
                self.driver.uc_click("span:contains('Searched the web')")
                sleep(random.uniform(3, 5))

                # Grab the 10 sources that Claude lists in the "Searched the web" box and stick them in our output dataframe as well
                sources = self._extract_sources()
                row["response_sources"] = json.dumps(sources)
                sleep(random.uniform(1, 3))
            except Exception as e:
                source = "No Sources Found."
            

            # screenshot capture if we found the tested article link cited in the response
            row["original_in_citations"] = 0
            for c in row["response_citations"]:
                if c == row["pageURL"]:
                    row["original_in_citations"] = 1
            
            if row["original_in_citations"] == 1:
                screenshot_path = f"screenshots_claude_{dates}/Article_{row_num}.png"
                row["screenshot_path"] = screenshot_path
                self.driver.save_screenshot(screenshot_path)  

        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_claude_{dates}/Errors/Article_{row_num}_Collecting_Sources_Error.png")
            print(f"Exception{e}")

        return row
    
    # Helper to extract the response from the ChatGPT model
    def _extract_response(self, row):
        # Get all matching elements
        elements = self.driver.find_elements(By.CSS_SELECTOR, ".font-claude-response-body")
        # Extract HTML from each element, stripping <span> tags while preserving
        # child nodes (including <a> tags) in their original DOM positions.
        response_parts = []
        # Just the raw text
        response_text_parts = []
        # Just the urls from the ahrefs in the response
        response_citations = []

        # adjust the DOM to just retain links and paragraphs. 
        for el in elements:
            cleaned_html = self.driver.execute_script(
                """
                const clone = arguments[0].cloneNode(true);
                const spans = Array.from(clone.querySelectorAll('span')).reverse();

                for (const span of spans) {
                    const parent = span.parentNode;
                    if (!parent) continue;

                    while (span.firstChild) {
                        parent.insertBefore(span.firstChild, span);
                    }
                    parent.removeChild(span);
                }

                // Remove SVG elements entirely
                clone.querySelectorAll('svg').forEach((svg) => svg.remove());

                // Keep <p> and <a> tags, but strip class attributes from them
                if ((clone.tagName || '').toLowerCase() === 'p') {
                    clone.removeAttribute('class');
                }
                if ((clone.tagName || '').toLowerCase() === 'a') {
                    clone.removeAttribute('class');
                }
                clone.querySelectorAll('p').forEach((p) => p.removeAttribute('class'));
                clone.querySelectorAll('a').forEach((a) => a.removeAttribute('class'));

                // Fix spacing artifacts (e.g., "word .") after span unwrapping
                const walker = document.createTreeWalker(clone, NodeFilter.SHOW_TEXT);
                let textNode;
                while ((textNode = walker.nextNode())) {
                    textNode.nodeValue = (textNode.nodeValue || '').replace(/\\s+([.,!?;:])/g, '$1');
                }

                // Preserve paragraph wrappers when the selected node is itself <p>
                if ((clone.tagName || '').toLowerCase() === 'p') {
                    return clone.outerHTML;
                }

                return clone.innerHTML;
                """,
                el,
            )

            response_parts.append(cleaned_html or "")

            hrefs = self.driver.execute_script(
                """
                const wrap = document.createElement('div');
                wrap.innerHTML = arguments[0] || '';
                return Array.from(wrap.querySelectorAll('a[href]'))
                    .map((a) => (a.getAttribute('href') || '').trim())
                    .filter(Boolean);
                """,
                cleaned_html,
            )
            response_citations.extend(hrefs or [])

            cleaned_text = self.driver.execute_script(
                """
                const wrap = document.createElement('div');
                wrap.innerHTML = arguments[0] || '';
                // Exclude anchor text from response_text
                wrap.querySelectorAll('a').forEach((a) => a.remove());
                return (wrap.innerText || '').replace(/\\s+([.,!?;:])/g, '$1');
                """,
                cleaned_html,
            )
            response_text_parts.append((cleaned_text or "").strip())

        response = "".join(response_parts)
        #print (response)
        row["response"] = response
        #print ("\n")
        response_text = "\n".join([part for part in response_text_parts if part])
        #print (response_text)
        row["response_text"] = response_text
        # Store unique hrefs in appearance order
        row["response_citations"] = json.dumps(list(dict.fromkeys(response_citations)))
    
    # Helper to extract the sources from the ChatGPT model
    def _extract_sources(self):
        results = []
        # referenced sources -- the list of 10 items referenced in the response. 
        # flex flex-row gap-3 items-center px-2 py-1.5 w-full rounded-md cursor-pointer transition-colors hover:bg-bg-200
        referenced_sources = self.driver.find_elements(By.CSS_SELECTOR, ".flex.flex-col.gap-1:not(.items-end) .flex.flex-row.gap-3")
        # flex flex-col gap-1
        print ("Sources found:", len(referenced_sources))
        for source in referenced_sources:
            items = source.find_elements(By.TAG_NAME, "div")
            source_name = items[1].text if len(items) > 1 else ""
            source_url = items[2].text if len(items) > 2 else ""
            results.append({
                "source_name": source_name,
                "url": source_url,
            })
        return results
  
def RunClaudeScraper():
    try:
        scraper = None
        df = None
        
        # Collect from the Gannett API: expected format is YYYY-MM-DD or YYYY-MM-DD_DD for multiple days
        try:
            dates = sys.argv[1]
        except:
            print("Need a date parameter after the filename in the form of YYYY-MM-DD or YYYY-MM-DD_DD for multiple days")
            sys.exit(1)
        
        df, num_rows = BaseScraper.get_API_data(dates, "claude") # type: ignore

        email, pwd = BaseScraper.get_login_creds("claude") # type: ignore

        # Create a scraper instance
        scraper = ClaudeScraper()

        # Prep the dataframe by adding the columns that will store the scraped data
        df = scraper.prep_data(df) # type: ignore
        #df = df[:5]

        scraper._login(email, pwd, dates)

        #sleep (1200)
        # Call the scraper on each row of the dataframe
        current_row = 1
        for idx, row in df.iterrows():
            df.loc[idx] = scraper._collect_data(row, current_row, dates)
            
            print(f"Finished article {current_row} of {num_rows}. {round(float(current_row/num_rows) * 100, 1)} percent completed.")
        
            # Saves csv after every row 
            #if current_row % 50 == 0:
            OUTPUT_DIR = Path("./data/")
            df.to_csv(OUTPUT_DIR / f"gannett_claude_{dates}.csv", index=False)
            print(f"Progress snapshot saved to 'gannett_claude_{dates}.csv'.")

            current_row += 1
            # delay could maybe vary depending on whether you're logged in with a pro account or not
            sleep(random.uniform(120, 125)) # added a delay here to avoid hitting rate limits


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
            OUTPUT_DIR = Path("./data/")
            df.to_csv(OUTPUT_DIR / f"gannett_claude_{dates}.csv", index=False)
            print(f"'gannett_claude_{dates}.csv' saved successfully.")

if __name__ == "__main__":
    RunClaudeScraper()