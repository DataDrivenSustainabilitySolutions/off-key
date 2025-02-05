import httpx


class PionixClient:

    def __init__(self, api_key: str, user_agent: str):
        self.base_url = "https://sc-production.schoneberg.pionix.net"
        self.api_key = api_key
        self.user_agent = user_agent

    async def get(self, endpoint, params=None):
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": f"Bearer {self.api_key}",
        }
        print(headers)
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/{endpoint}",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            return response.json()
