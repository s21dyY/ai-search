
# ### Site Codes to use with the Gannett API
# NABJ - Akron Beacon Journal (beaconjournal.com)  
# NCOD - The Columbus Dispatch (dispatch.com)  
# NDNJ - Daytona Beach News-Journal (news-journalonline.com)  
# NFTU - Florida Times-Union (jacksonville.com)  
# NOKL - The Oklahoman (oklahoman.com)  
# NPPP - The Palm Beach Post (palmbeachpost.com)  
# NPRJ - The Providence Journal (providencejournal.com)  
# NSHT - Herald-Tribune (heraldtribune.com)  
# PAPP - Asbury Park Press (app.com)  
# PCIN - The Cincinnati Enquirer (cincinnati.com)  
# PDEM - The Des Moines Register (desmoinesregister.com)  
# PDTF - Detroit Free Press (freep.com)  
# PDTN - Detroit News (detroitnews.com)  
# PFTM - The News-Press (news-press.com)  
# PIND - The Indianapolis Star (Indystar.com)  
# PKNS - Knoxville News Sentinel (knoxnews.com)  
# PLOU - Courier-Journal (courier-journal.com)  
# PMJS - Journal Sentinel (jsonline.com)  
# PNAS - The Tennessean (tennessean.com)  
# PNDN - Naples Daily News (naplesnews.com)  
# PNJM - The Record (northjersey.com)  
# PPHX - The Arizona Republic (azcentral.com)  
# PROC - Democrat and Chronicle (democratandchronicle.com)  
# PTCN - TC Palm (tcpalm.com)  
# PWES - The Journal News (lohud.com)  
# PWIL - The News Journal (delawareonline.com)  
# USAT - USA TODAY (usatoday.com)

# Imports
import requests
import sys
import json
import pandas as pd
import re
from pathlib import Path

# This class wraps the Gannett API for getting content
class GannettAPI:
    def __init__(self):
        # Global variables
        self.api_url = "https://content-api.gannettdigital.com/assets"
        ## Add your API key here
        self.api_key = ""
        
    # Grab data from a site based on a site code (listed above) and a date range as YYYY-MM-DD
    def _get_site_data_by_date(self, site_code, start_date, end_date, sample=None):
        headers = {'x-api-key': self.api_key,
            'content-type': 'application/json',
            'x-sitecode': 'USAT'}
        params = {
            "types": ["text"],
            "site_code": site_code,
            "start_date": start_date,
            "end_date": end_date,
            "size": 2000,
            "offset": 0,
            "api_key": self.api_key
        }
        query = f"""
            query {{
            searchAssets(template: "asset_on_day_by_site", parameters: "{json.dumps(params).replace('"', '\\"')}") {{
                assets {{
                headline
                ... on text {{
                    fullText
                }}
                type
                publishDate
                pageURL {{
                    long
                }}
                classificationV2 {{
                    section
                    subsection
                }}
                
                }}
            }}
            }}
            """
        r = requests.get(self.api_url, params={"query": query}, headers=headers)
        data = r.json()["data"]["searchAssets"]["assets"]

        df = pd.json_normalize(data)
        df.rename(columns={"pageURL.long": "pageURL", "classificationV2.section": "section", "classificationV2.subsection": "subsection"}, inplace=True)
        df['publishDate'] = pd.to_datetime(df['publishDate'], errors='coerce')
        print ("Num Items:", df.shape)
        
        if sample is not None:
            return df.sample(sample, random_state=42)
        return df

    # Collect data from multiple sites in a time frame
    def _get_sites_data_by_date(self,site_codes, start_date, end_date, sample=None):
        df = None
        for s in site_codes:
            try:
                df2 = self._get_site_data_by_date(s, start_date, end_date, sample)
            except Exception as e:
                print(f"API ERROR: Double check your dates. Error: {e}")
                sys.exit(1)

            if df is None:
                df = df2
            else:
                df = pd.concat([df, df2])
        return df
    
    # Collect data from multiple sites in a time frame
    def test_api(self, dates):
        self._validate_input(dates)

        # Update the site codes here
        #site_codes = ["PDTF", "PPHX", "PMJS", "PNAS", "PIND", "PCIN", "NCOD", "PNJM", "PAPP", 
        #            "NPPP", "PDEM", "NOKL", "PKNS", "PWIL", "PNDN", "PROC", "PLOU", "USAT"]
        site_codes = ["USAT"]
        
        year, month, days = dates.split('-')

        if '_' in days:
            return GannettAPI()._get_sites_data_by_date(site_codes, f"{year}-{month}-{days.split('_')[0]}", f"{year}-{month}-{days.split('_')[1]}").reset_index(drop=True) # type: ignore
        else:
            return GannettAPI()._get_sites_data_by_date(site_codes, f"{year}-{month}-{days}", f"{year}-{month}-{days}").reset_index(drop=True) #type: ignore
    
    @staticmethod
    def _validate_input(dates):
        # validate the expected input format of YYYY-MM-DD or YYYY-MM-DD_DD for multiple days
        if not re.match(r'^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])(_(0[1-9]|[12][0-9]|3[01]))?$', dates):
            print("API ERROR: Date must be in YYYY-MM-DD or YYYY-MM-DD_DD for multiple days (e.g., 2025-04-07 or 2025-04-07_08)")
            sys.exit(1)
        elif '_' in dates:
            if int(dates.split('-')[2].split('_')[0]) > int(dates.split('-')[2].split('_')[1]):
                print("API ERROR: First day in the range must be before the second.")
                sys.exit(1)
            
# can run the file directly to output data in a .csv, just specify the year, month and day: expected format YYYY-MM-DD or YYYY-MM-DD_DD for multiple days in one month
if __name__ == "__main__":
    try:
        dates = sys.argv[1]
    except:
        print("Need a date parameter after the filename in the form of YYYY-MM-DD or YYYY-MM-DD_DD for multiple days")
        sys.exit(1)

    OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data"   # repo data/ (gitignored)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / f"gannett_API_data_{dates}.csv"    
    GannettAPI().test_api(dates).to_csv(output_path, index=False)
    print(f"'gannett_API_data_{dates}.csv' saved.")