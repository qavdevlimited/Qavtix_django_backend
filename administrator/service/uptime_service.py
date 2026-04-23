import requests
import time
from decouple import config

class UptimeService:
    URL = "https://api.uptimerobot.com/v2/getMonitors"

    @staticmethod
    def get_uptime():
        api_key = config("UPTIMEROBOT_API_KEY")
        
        # Calculate the 30-day window in Unix timestamps
        now = int(time.time())
        thirty_days_ago = now - (30 * 24 * 60 * 60)
        custom_range = f"{thirty_days_ago}_{now}"

        payload = {
            "api_key": api_key,
            "format": "json",
            "custom_uptime_ranges": custom_range,
            "logs": 1 # Optional: helpful for debugging incidents
        }

        try:
            response = requests.post(UptimeService.URL, data=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            monitors = data.get("monitors", [])
            if not monitors:
                return 0.0

            monitor = monitors[0]
            
            # The API returns custom_uptime_ranges as a string of percentages 
            # delimited by a hyphen if multiple ranges are requested.
            ratio = monitor.get("custom_uptime_ranges", "0")
            
            return round(float(ratio), 2)
            
        except (requests.RequestException, ValueError, IndexError) as e:
            print(f"Error fetching uptime: {e}")
            return 0.0