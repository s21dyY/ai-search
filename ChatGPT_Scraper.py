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
from Prompt_Generator import PromptGenerator

class ChatGPTScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.url = "https://chatgpt.com/"
        self.url_auth = "https://chat.openai.com/auth/login"
        # Capture search activity before the guest UI hides it after answering.
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": r'''
            (() => {
                const originalFetch = window.fetch;
                const sources = new Map();
                const citations = new Map();
                window.__aiSearchResults = {sources: [], citations: [], error: null};
                async function capture(response) {
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let pending = '';
                    try {
                        while (true) {
                            const {value, done} = await reader.read();
                            pending += decoder.decode(value || new Uint8Array(), {stream: !done});
                            let end;
                            while ((end = pending.indexOf('\n')) >= 0) {
                                const line = pending.slice(0, end);
                                pending = pending.slice(end + 1);
                                if (!line.trim()) continue;
                                const record = JSON.parse(line);
                                const reasoning = record.status?.reasoning;
                                for (const item of [...(reasoning?.items || []), reasoning?.activeItem]) {
                                    for (const group of item?.searchSources?.groups || []) {
                                        for (const entry of group.entries || []) {
                                            if (!entry.url) continue;
                                            const url = entry.url.replace('?utm_source=chatgpt.com', '');
                                            sources.set(url, {url, headline: entry.title || '', snippet: entry.snippet || ''});
                                        }
                                    }
                                }
                                const components = record.dil?.appData?.opGenui?.componentResults;
                                if (components) {
                                    citations.clear();
                                    for (const component of Object.values(components)) {
                                        if (component.componentName !== 'Cite') continue;
                                        for (const entry of component.state?.items || []) {
                                            if (!entry.url) continue;
                                            const url = entry.url.replace('?utm_source=chatgpt.com', '');
                                            citations.set(url, {url, headline: entry.title || '', snippet: entry.snippet || ''});
                                        }
                                    }
                                }
                                window.__aiSearchResults.sources = [...sources.values()];
                                window.__aiSearchResults.citations = [...citations.values()];
                            }
                            if (done) break;
                        }
                    } catch (error) {
                        window.__aiSearchResults.error = String(error);
                    } finally {
                        reader.releaseLock();
                    }
                }
                window.fetch = async function(...args) {
                    const response = await originalFetch.apply(this, args);
                    if (response.url.includes('/unauth-mweb/conversation/updates')) capture(response.clone());
                    return response;
                };
            })();
        '''})
    
    # Prep the dataframe by adding the columns that will store the scraped data
    def prep_data(self, df):
        # Add columns to the dataframe to store the scraped data
        # Prompt is the input prompt that is used to query the model
        # Response_text is the response from the model
        # Response_citations is a JSON of the citations that the model cited in the response
        # Response_search_results includes guest search-activity results, which may overlap with citations.
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
            print(f"ChatGPT login failed: {e}")
        
    # Query the ChatGPT model with a prompt
    def _query_chatgpt(self, query, row_num, dates):
        # self.driver.uc_open(self.url)
        self.driver.default_get(self.url)  # Navigate synchronously in the current chat tab.
        sleep(random.uniform(1, 2))
        # Delete what was in the input box
        # textarea = self.driver.find_element("div#prompt-textarea.ProseMirror  ")
        textarea = WebDriverWait(self.driver, 20).until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "div#prompt-textarea.ProseMirror, textarea#mobile-composer-prompt")
        ))
        # Enable web search on the guest composer without changing the query.
        if textarea.get_attribute("id") == "mobile-composer-prompt":
            self.driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Add files and more"]').click()
            self.driver.find_element(By.CSS_SELECTOR, 'button[data-octane-web-search-toggle]').click()
        # textarea.send_keys(Keys.CONTROL, "a")  # Previous selection shortcut did not clear reliably on macOS.
        # textarea.send_keys(Keys.BACKSPACE)
        textarea.clear()

        # self.driver.send_keys("div#prompt-textarea.ProseMirror  ", BaseScraper.remove_non_bmp(query))
        textarea.send_keys(BaseScraper.remove_non_bmp(query))
        sleep(random.uniform(1, 3))
        request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # self.driver.send_keys("#prompt-textarea", Keys.ENTER)
        textarea.send_keys(Keys.ENTER)
        sleep(random.uniform(20, 25))
        return request_time
        
    # Collect the data from the ChatGPT model for one row of the input data frame this is applied to
    def _collect_data(self, row, row_num, dates):
        # added a delay here so we don't hit the gpt-4o limit of 80 messages / 3 hrs. 
        sleep(random.uniform(20, 30))
        try:
            # Generate a natural-language prompt from the headline + keywords
            PROMPT = self.prompt_generator.generate(
                row["headline"],
                row.get("keywords", "") or "",
            )
            row["prompt"] = PROMPT
            row["request_time"] = self._query_chatgpt(PROMPT, row_num, dates)

            # Extract the response HTML
            row["response_text"] = self._extract_response()
            
            # And then extract all of the source information broken into citations and search results
            try:
                # self.driver.uc_click("button.group\\/footnote")
                sources_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button.group\\/footnote")
                if sources_buttons:
                    sources_buttons[0].click()
                    sleep(random.uniform(3, 5))

                for header, column, suffix in (
                    ("Citations", "response_citations", "citations"),
                    ("More", "response_search_results", "search_results"),
                ):
                    try:
                        sources = self._extract_sources(header)
                    except Exception as e:
                        detail = str(e).split("Stacktrace:")[0].strip()
                        row[column] = f"ERROR: {header} source extraction failed ({type(e).__name__}): {detail}"
                        print(f"Article {row_num}: {row[column]}")
                        continue

                    if sources is None:
                        row[column] = f"ERROR: {header} sources unavailable in this response."
                        continue

                    row[column] = json.dumps(sources)
                    row[f"original_in_{suffix}"] = row[f"republisher_in_{suffix}"] = 0
                    for source in sources:
                        if source["url"] in row["pageURL"]:
                            row[f"original_in_{suffix}"] = 1

                        # Truncated headline matching is only a possible republisher signal.
                        h = source["headline"].split(" ...")[0]
                        if h and h in row["headline"] and source["url"] not in row["pageURL"] and "en.wikipedia.org" not in source["url"]:
                            row[f"republisher_in_{suffix}"] = 1

            except Exception as e:
                detail = str(e).split("Stacktrace:")[0].strip()
                for column in ("response_citations", "response_search_results"):
                    if row[column] is None:
                        row[column] = f"ERROR: Source collection failed ({type(e).__name__}): {detail}"
                print(f"Article {row_num}: source extraction failed: {e}")

            # if any copies were detected make a screen shot
            if row["original_in_citations"] or row["republisher_in_citations" ] or row["original_in_search_results"] or row ["republisher_in_search_results"]:
                screenshot_path = f"screenshots_gpt_{dates}/Article_{row_num}_SourceUsed.png"
                row["screenshot_path"] = screenshot_path
                self.driver.save_screenshot(screenshot_path)    

        except Exception as e:
            detail = str(e).split("Stacktrace:")[0].strip()
            for column in ("response_citations", "response_search_results"):
                if row[column] is None:
                    row[column] = f"ERROR: Sources not collected because article collection failed ({type(e).__name__}): {detail}"
            print(f"Article {row_num}: collection failed: {e}")

        return row
    
    # Helper to extract the response from the ChatGPT model
    def _extract_response(self):
        # response = self.driver.find_element(By.CSS_SELECTOR, ".markdown.prose").get_attribute("innerHTML")
        response = WebDriverWait(self.driver, 60).until(EC.visibility_of_element_located(
            (By.CSS_SELECTOR, '.markdown.prose, [data-message-role="assistant"][data-message-complete] section[aria-label="DIL content"]')
        )).get_attribute("innerHTML")

        return response
    
    # Helper to extract the sources from the ChatGPT model
    def _extract_sources(self, header_text):
        results = []

        # Find the section based on the header text
        # header_element = self.driver.find_element(By.XPATH, f"//li[text()='{header_text}']")
        headers = self.driver.find_elements(By.XPATH, f"//li[text()='{header_text}']")
        if not headers:
            # Guest search results arrive in search activity instead of a More section.
            if header_text == "More":
                # return None  # Previous implementation required the legacy More heading.
                captured = self.driver.execute_script("return window.__aiSearchResults || null")
                if captured and captured["error"]:
                    raise RuntimeError(f"Guest search-result capture failed: {captured['error']}")
                return (captured["sources"] or None) if captured else None
            # Use the guest response's citation records; the previous popover implementation remains below as fallback.
            captured = self.driver.execute_script("return window.__aiSearchResults || null")
            if captured and captured["citations"]:
                return captured["citations"]
            links = self.driver.find_elements(By.CSS_SELECTOR,
                '[data-message-role="assistant"][data-message-complete] section[aria-label="DIL content"] a[href^="http"]')
            results = [{"url": link.get_attribute("href").replace("?utm_source=chatgpt.com", ""),
                        "headline": link.text, "snippet": ""} for link in links]

            # Guest source cards open URLs through window.open instead of anchor hrefs.
            triggers = self.driver.find_elements(By.CSS_SELECTOR,
                '[data-message-role="assistant"][data-message-complete] [role="button"][aria-haspopup="dialog"]')
            if not triggers:
                return results or None
            self.driver.execute_script('''
                window.__aiSearchURLs = [];
                window.__aiSearchOpen = window.open;
                window.__aiSearchClick = event => {
                    const card = event.target.closest('button[aria-label^="Open "]');
                    // if (card) window.__aiSearchCard = card.innerText; // Previous empty-button lookup.
                    if (card) window.__aiSearchCard = card.parentElement.innerText;
                };
                document.addEventListener('click', window.__aiSearchClick, true);
                window.open = url => {
                    window.__aiSearchURLs.push({url: String(url), text: window.__aiSearchCard});
                    return null;
                };
            ''')
            try:
                for trigger in triggers:
                    if trigger.get_attribute("aria-expanded") != "true":
                        trigger.send_keys(Keys.ENTER)
                    popover = WebDriverWait(self.driver, 10).until(EC.visibility_of_element_located(
                        (By.ID, trigger.get_attribute("aria-controls"))
                    ))
                    for button in popover.find_elements(By.CSS_SELECTOR, 'button[aria-label^="Open "]'):
                        self.driver.execute_script("window.__aiSearchURLs = []")
                        # button.click()  # Previous pointer click hits overlapping title text.
                        button.send_keys(Keys.ENTER)
                        source = WebDriverWait(self.driver, 10).until(
                            lambda driver: driver.execute_script("return window.__aiSearchURLs.shift() || null"))
                        lines = [line for line in source["text"].splitlines() if line]
                        url = source["url"].replace("?utm_source=chatgpt.com", "")
                        if not any(source["url"] == url for source in results):
                            results.append({"url": url, "headline": lines[1] if len(lines) > 1 else lines[0],
                                            "snippet": ""})
                    trigger.send_keys(Keys.ENTER)
            finally:
                self.driver.execute_script('''
                    window.open = window.__aiSearchOpen;
                    document.removeEventListener('click', window.__aiSearchClick, true);
                    delete window.__aiSearchURLs;
                    delete window.__aiSearchOpen;
                    delete window.__aiSearchClick;
                    delete window.__aiSearchCard;
                ''')
            return results
        header_element = headers[0]
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

        # Account-free by default. Uncomment both login lines to restore sign-in.
        # email, pwd = BaseScraper.get_login_creds("chatgpt")

        # Create a scraper instance
        scraper = ChatGPTScraper()
        scraper.prompt_generator = PromptGenerator()

        # Prep the dataframe by adding the columns that will store the scraped data
        df = scraper.prep_data(df)

        # scraper._login(email, pwd, dates)

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
