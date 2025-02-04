from urllib.parse import quote

from backend.app.clients.base import BaseClient


class PionixClient(BaseClient):
    def __init__(self, api_key, user_agent):
        super().__init__(
            base_url="https://sc-production.schoneberg.pionix.net",
            api_key=api_key,
            user_agent=user_agent,
        )

    def get_chargers(self):
        return self._get("api/chargers")

    def get_telemetry(self, charger_id, start_date, end_date):
        endpoint = (
            f"api/chargers/{charger_id}/telemetry/%2FTopLevelPart%2FTelemetryDouble"
        )
        params = f"StartDate={quote(start_date)}&EndDate={quote(end_date)}"
        return self._get(endpoint, params=params)
