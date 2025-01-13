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
    api_key="eyJhbGciOiJSUzI1NiIsImtpZCI6IjQwZDg4ZGQ1NWQxYjAwZDg0ZWU4MWQwYjk2M2RlNGNkOGM0ZmFjM2UiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJodHRwczovL3NlY3VyZXRva2VuLmdvb2dsZS5jb20vc3VtbWl0ZWVyLWNsb3VkLWRldiIsImF1ZCI6InN1bW1pdGVlci1jbG91ZC1kZXYiLCJhdXRoX3RpbWUiOjE3MzY3ODM5NTIsInVzZXJfaWQiOiI0QkVrY1BVbFdyWE01NGhyMG1ONHc2MFd1eG0yIiwic3ViIjoiNEJFa2NQVWxXclhNNTRocjBtTjR3NjBXdXhtMiIsImlhdCI6MTczNjc4Mzk1MiwiZXhwIjoxNzM2Nzg3NTUyLCJlbWFpbCI6Im9saXZlci5oZW5uaG9lZmVyQGgta2EuZGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsImZpcmViYXNlIjp7ImlkZW50aXRpZXMiOnsiZW1haWwiOlsib2xpdmVyLmhlbm5ob2VmZXJAaC1rYS5kZSJdfSwic2lnbl9pbl9wcm92aWRlciI6InBhc3N3b3JkIn19.mf2mqc-MRe-geQdsVL3n3C24Dto4oVOgaS2AvD6P-xLS4kDhwPTCaepz9_n8C2OSSLUZwnPKVsFdgdagkm8E7lZLCiYAkLPrvjkstH5ErIpNX9WOpiWoFkglTNxH8c9vuHSDPkOO1eE-isX3_o9dZPXlLGAmsyXFozb1xlAE6V81_wKjIreQzG0mZjjsivWfLW4b6gG8A7WJUi2QbuVX4R8iZ59LhFyQV2zA0DUBEXLSYP-jHG3U-HVaWieuPAYlq_Om6sjm54QrsWDTfrykVyMs3fZO66NykhBHJ_MgwNYWFnT7wcbDMxbB7lzv72TLF6fDH_fmm8hwsmxO7kMfIw",
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
scheduler.add_job(fetch_chargers_data, "interval", seconds=3)
#scheduler.add_job(fetch_telemetry_data, "interval", seconds=10, args=[1])


# FastAPI endpoints
@app.get("/chargers")
def get_chargers():
    try:
        chargers = pionix_client.get_chargers()
        return {"chargers": chargers}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/telemetry/{charger_id}")
def get_telemetry(charger_id: int, start_date: str, end_date: str):
    try:
        telemetry = pionix_client.get_telemetry(charger_id, start_date, end_date)
        return {"telemetry": telemetry}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
