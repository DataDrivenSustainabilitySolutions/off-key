from typing import Optional

from backend.api.clients.pionix import PionixClient
from fastapi import FastAPI, HTTPException
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta, timezone
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI()

# Initialize the PionixClient
pionix_client = PionixClient(
    api_key="eyJhbGciOiJSUzI1NiIsImtpZCI6IjBhYmQzYTQzMTc4YzE0MjlkNWE0NDBiYWUzNzM1NDRjMDlmNGUzODciLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vc3VtbWl0ZWVyLWNsb3VkLWRldiIsImF1ZCI6InN1bW1pdGVlci1jbG91ZC1kZXYiLCJhdXRoX3RpbWUiOjE3MzY4NjIzODQsInVzZXJfaWQiOiI0QkVrY1BVbFdyWE01NGhyMG1ONHc2MFd1eG0yIiwic3ViIjoiNEJFa2NQVWxXclhNNTRocjBtTjR3NjBXdXhtMiIsImlhdCI6MTczNjg2NjQ5MywiZXhwIjoxNzM2ODcwMDkzLCJlbWFpbCI6Im9saXZlci5oZW5uaG9lZmVyQGgta2EuZGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsImZpcmViYXNlIjp7ImlkZW50aXRpZXMiOnsiZW1haWwiOlsib2xpdmVyLmhlbm5ob2VmZXJAaC1rYS5kZSJdfSwic2lnbl9pbl9wcm92aWRlciI6InBhc3N3b3JkIn19.bt2OhGsxkbIsC8EDdHszShyUrHR48Br1lzinEd8Vfnf2qmA4_eT8ZZ4fJozN_G8Xds-0p4aPNTsaiZ5tTDT1qBPDHUxAnu7h6Vw53564zae_VBpTW4WVPzjsxLYBCJu1IWcBam96mZP8pra4dhdzUJ_9cUzEtxcezIsGJ09i3Jg2FjhnckQqT2vuVHa345icb-EpMBEH1P6oAfLRc4lSDByxFKMsyCcH_ET-YEG3amk_jwth8qO128hd1rBwmzL9dvBmd5Mv2Bcyj9psPD2g0dun2z0QxcJ5JaijkbY8gdiOXSGQFdjKn-05nmndzDl42k___CxCtQ_WlOXxCTgVGg",
    user_agent="hka-biflex-pdm/1.0 (oliver.hennhoefer@h-ka.de)",
)

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.start()


# Function to fetch chargers data
def fetch_chargers_data():
    try:
        chargers = pionix_client.get_chargers()
        logger.info(f"Fetched chargers data: {chargers}")
    except Exception as e:
        logger.error(f"Error fetching chargers data: {e}")


# Function to fetch telemetry data for a specific charger
def fetch_telemetry_data(charger_id):
    try:
        now = datetime.now(timezone.utc)  # Use timezone-aware datetime
        start_date = (now - timedelta(minutes=10)).isoformat()  # Last 10 minutes
        end_date = now.isoformat()
        telemetry = pionix_client.get_telemetry(charger_id, start_date, end_date)
        logger.info(f"Fetched telemetry data for charger {charger_id}: {telemetry}")
    except Exception as e:
        logger.error(f"Error fetching telemetry data for charger {charger_id}: {e}")


# Schedule tasks
#scheduler.add_job(fetch_chargers_data, "interval", seconds=3)
charger_id = "c662a262-f9aa-49b4-8b4f-ea3237948d73"
#scheduler.add_job(fetch_telemetry_data, "interval", seconds=3, args=[charger_id])


# FastAPI endpoints
@app.get("/chargers")
def get_chargers():
    try:
        chargers = pionix_client.get_chargers()
        return {"chargers": chargers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/telemetry/{charger_id}")
def get_telemetry(charger_id: str, start_date: Optional[str] = None, end_date: Optional[str] = None,):
    # Set default values if not provided
    if not start_date or not end_date:
        now = datetime.now(timezone.utc)
        start_date = (now - timedelta(minutes=10)).isoformat()  # Last 10 minutes
        end_date = now.isoformat()
    try:
        telemetry = pionix_client.get_telemetry(charger_id, start_date, end_date)
        return {"telemetry": telemetry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
