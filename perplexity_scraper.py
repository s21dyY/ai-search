# Scraping using method from here: https://www.zenrows.com/blog/selenium-cloudflare-bypass#seleniumbase
# Selenium base API for reference: https://seleniumbase.io/help_docs/method_summary/#seleniumbase-methods-api-reference

import random
from datetime import datetime
from time import sleep
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import sys
from Chatbot_Scraper import BaseScraper

# Perplexity scraper
class PerplexityScraper(BaseScraper):
    def __init__(self):
        super().__init__()
        self.url = "https://www.perplexity.ai"

    # Prep the dataframe by adding the columns that will store the scraped data
    def _prep_data(self, df):
        # Prompt is the prompt that was used the query the model
        # Response text is the response from the model
        # Response sources is a list of sites the LLM cited
        # Original in sources is a flag to indicate if the original article was cited in the sources list
        df[["prompt", "response_text", "number_of_sources", "response_sources", "original_in_sources", "screenshot_path", "request_time"]] = None
        return df

    def _query_perplexity(self, query, row_num, dates):
        try:
            self.driver.uc_open(self.url)
            sleep(random.uniform(1, 2))
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "textarea")))
            textarea = self.driver.find_element(By.TAG_NAME, "textarea")

            # delete whatever was in the input box
            textarea.send_keys(Keys.CONTROL, "a")
            textarea.send_keys(Keys.BACKSPACE)
            # put the new query in the input box
            textarea.send_keys(BaseScraper.remove_non_bmp(query))
            sleep(random.uniform(1, 3))
            request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            textarea.send_keys(Keys.ENTER)
            sleep(random.uniform(25, 30))
            return request_time

        except Exception as e:
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
            self.driver.save_screenshot(f"screenshots_perplexity_{dates}/Errors/Article_{row_num}_Query_Error.png")
            print(f"Exception{e}")

    # query the model and extract the response and sources for one row of an input data frame at a time
    def _collect_data(self, row, row_num, dates):
        sleep(random.uniform(30, 35))
        try:
            # Send the prompt
            PROMPT = f'Tell me about "{row["headline"]}"'
            row["request_time"] = self._query_perplexity(PROMPT, row_num, dates)
            row["prompt"] = PROMPT

            # Extract the response HTML while removing emojis
            WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".prose")))
            row["response_text"] = BaseScraper.remove_non_bmp(self.driver.find_element(By.CSS_SELECTOR, ".prose").get_attribute("innerHTML"))

            # click the sources button
            self.driver.click(By.CSS_SELECTOR, "[data-testid='answer-mode-tabs-tab-sources']")

            # get the number of sources (based on number next to the sources button)
            sources_num = int(self.driver.find_element(By.TAG_NAME, "number-flow-react").get_attribute("aria-label"))
            row["number_of_sources"] = sources_num

            # get the link for each source (cut off after tld)
            sites_visited = []
            sources = self.driver.find_elements(By.CSS_SELECTOR, 'div.gap-md.relative.items-start div.gap-sm.flex.flex-row.items-center div.line-clamp-1.font-sans.text-xs.text-textOff')
            try:
                for i in range(sources_num):
                    site = sources[i].text.split('/')[0]
                    sites_visited.append(site)

            except IndexError:
                # save the list of sources anyway
                pass

            row["response_sources"] = sites_visited

            for s in sites_visited:
                if s in row["pageURL"]:
                    row["original_in_sources"] = 1

            # make a screen shot if Perplexity used a Gannett site as a source
            if row["original_in_sources"]:
                screenshot_path = f"screenshots_perplexity_{dates}/Article_{row_num}_SourceUsed.png"
                row["screenshot_path"] = screenshot_path
                WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
                self.driver.save_screenshot(screenshot_path)

        except Exception as e:
            # special case if Perplexity used no sources and there's no "Sources" button
            if "data-testid='answer-mode-tabs-tab-sources'" in str(e):
                row["number_of_sources"] = 0
            else:
                # let the calling try/catch block handle other exceptions
                raise

        return row

# Instantiates and uses the PerplexityScraper. Automatically pulls API data for the given date(s) from the Gannett_API.py file
def RunPerplexityScraper():
    try:
        scraper = None
        df = None
        
        # Collect from the Gannett API: expected format is YYYY-MM-DD or YYYY-MM-DD_DD for multiple days
        try:
            dates = sys.argv[1]
        except:
            print("Need a date parameter after the filename in the form of YYYY-MM-DD or YYYY-MM-DD_DD for multiple days")
            sys.exit(1)
        
        df, num_rows = BaseScraper.get_API_data(dates, "perplexity")

        scraper = PerplexityScraper()

        # Prep the dataframe by adding the columns that will store the scraped data
        df = scraper._prep_data(df)

        # Call the scraper on each row of the dataframe
        current_row = 1
        for idx, row in df.iterrows():
            try:
                df.loc[idx] = scraper._collect_data(row, current_row, dates)
            except Exception as e:
                if not e is KeyboardInterrupt:
                    # restart the scraper if the Perplexity page goes blank.
                    print("Perplexity page went blank. Restarting the scraper...")
                    scraper.close()
                    sleep(random.uniform(60, 65))
                    scraper = PerplexityScraper()
                    sleep(random.uniform(60, 65))

                    # Retry once
                    try:
                        df.loc[idx] = scraper._collect_data(row, current_row, dates)
                    except Exception as e:
                        print(f"Retry failed on row {current_row}. Skipping. Error: {str(e)}")
                        df.loc[idx] = None
                        WebDriverWait(scraper.driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
                        try:
                            scraper.driver.save_screenshot(f"screenshots_perplexity_{dates}/Errors/Article_{current_row}_Collect_Error.png")
                        except:
                            pass

            print(f"Finished article {current_row} of {num_rows}. {round(float(current_row/num_rows) * 100, 1)} percent completed.")

            # backup the progress every 50 articles
            if current_row % 50 == 0:
                df.to_csv(f"gannett_perplexity_{dates}.csv", index=False)
                print(f"Progress snapshot saved to 'gannett_perplexity_{dates}.csv'.")

            current_row += 1

    # catch any unhandled errors or user interrupts
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt caught. Saving progress...")

    except Exception as e:
        print(f"\nEncountered the following error:\n{str(e)}\n\nSaving progress...")

    # clean up and save
    finally:
        if scraper:
            scraper.close()
        
        if df is not None:
            df.to_csv(f"gannett_perplexity_{dates}.csv", index=False)
            print(f"'gannett_perplexity_{dates}.csv' saved successfully.")

if __name__ == "__main__":
    RunPerplexityScraper()