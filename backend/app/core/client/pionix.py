import httpx

from ...core.logs import logger


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
        url = f"{self.base_url}/{endpoint}"
        logger.info(f"GET from {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                params=params,
            )
            logger.info(f"GET response {response}")

            logger.warning(f"Response raw text {response.text}")

            response.raise_for_status()
            return response.json()
