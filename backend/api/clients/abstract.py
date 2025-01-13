import requests


class APIClient:
    def __init__(self, base_url, api_key, user_agent):
        self.base_url = base_url
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate, br, zstd",
            }
        )

    def _get(self, endpoint, params=None):
        url = f"{self.base_url}/{endpoint}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint, data=None, json=None):
        url = f"{self.base_url}/{endpoint}"
        response = self.session.post(url, data=data, json=json)
        response.raise_for_status()
        return response.json()
