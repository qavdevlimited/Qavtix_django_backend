import requests
from decouple import config

class UptimeService:
    # Use the Friendly Name set in your UptimeRobot Dashboard
    DEFAULT_MONITOR_NAME = "Login Endpoint" 
    UPTIME_ROBOT_API_URL = "https://api.uptimerobot.com/v2/getMonitors"

    @staticmethod
    def get_uptime():
        """
        Fetches the 30-day uptime ratio for the primary monitor.
        Returns a float (e.g., 99.982).
        """
        try:
            api_key = config("UPTIMEROBOT_API_KEY")
            
            # We request 'custom_uptime_ratios' for the last 30 days
            payload = {
                "api_key": api_key,
                "format": "json",
                "custom_uptime_ratios": "30", # Gets ratio for last 30 days
                "logs": 0 # Not needed for ratio calculation
            }

            response = requests.post(
                UptimeService.UPTIME_ROBOT_API_URL, 
                data=payload, 
                timeout=10
            )
            
            response.raise_for_status()
            data = response.json()
            monitors = data.get("monitors", [])

            if not monitors:
                print("UptimeService: No monitors found in account.")
                return 100.0

            
            # Adjust the lambda if you have multiple monitors
            monitor = next(
                (m for m in monitors if UptimeService.DEFAULT_MONITOR_NAME.lower() in m.get("friendly_name", "").lower()),
                monitors[1] 
                
            )
            print(monitors[1])

            # Get the ratio string (e.g., "99.950")
            ratio_str = monitor.get("custom_uptime_ratios", "100")
            
            # If for some reason ratio isn't returned, fallback to all_time
            if not ratio_str:
                ratio_str = monitor.get("all_time_uptime_ratio", "100")

            return round(float(ratio_str), 3)

        except Exception as e:
            print(f"UptimeService Error: {e}")
            # Return 100.0 as a safe fallback so the UI doesn't break
            return 100.0
