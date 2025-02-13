
# ### Site Codes to use with the Gannett API
# NAAS - Austin American Statesman (statesman.com)  
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
# 

# Imports
import requests
import json
import pandas as pd
from datetime import datetime

# This class wraps the Gannett API for getting content
class GannettAPI:
    def __init__(self):
        # Global variables
        self.api_url = "https://content-api.gannettdigital.com/assets"
        self.api_key = "FoOhYWDSfYo79SVysxvMTNCezUVyQIAf"
        
    # Grab data from a site based on a site code (listed above) and a date range as YYYY-MM-DD
    def get_site_data_by_date(self, site_code, start_date, end_date, sample=None):
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
        print (df.shape)
        if sample is not None:
            return df.sample(sample, random_state=42)
        return df

    # Collee data from multiple sites in a time frame
    def get_sites_data_by_date(self,site_codes, start_date, end_date, sample=None):
        df = None
        for s in site_codes:
            df2 = self.get_site_data_by_date(s, start_date, end_date, sample)
            if df is None:
                df = df2
            else:
                df = pd.concat([df, df2])
        return df
    
    # Function demonstrates to to collect data from multiple sites in a time frame
    def test_api(self):
        # Example usage showing how to get data from multiple sites in a time frame, here sampled to a single random article from each
        site_codes = ["PDTF", "PPHX", "PMJS", "PNAS", "PIND", "PCIN", "NCOD", "PNJM", "PAPP", 
                    "NPPP", "NAAS", "PDEM", "NOKL", "PKNS", "PWIL", "PNDN", "PROC", "PLOU", "USAT"]
        df = GannettAPI().get_sites_data_by_date(site_codes, "2024-12-09", "2024-12-10", sample=1)
        # Note, to filter to investigations do something like this:
        #df_investigations = df[(df['section']=="news") & (df["subsection"]=="investigations")].copy()
        df.to_csv("gannett_data_test.csv", index=False)
        print(df.head())    

GannettAPI().test_api()


