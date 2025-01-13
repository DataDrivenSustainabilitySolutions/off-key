import requests
import psycopg2
from datetime import datetime
import time
import os

# External API configuration
EXTERNAL_API_URL = "https://api.example.com/data"
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "timescaledb"),
    "user": os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "database": os.getenv("DB_NAME", "timeflux"),
}


def fetch_data():
    response = requests.get(EXTERNAL_API_URL)
    if response.status_code == 200:
        return response.json()
    return None


def write_to_db(data):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    query = """
    INSERT INTO sensor_data (timestamp, value)
    VALUES (%s, %s);
    """
    cursor.execute(query, (datetime.now(), data["value"]))
    conn.commit()
    cursor.close()
    conn.close()


def run_fetcher():
    while True:
        data = fetch_data()
        if data:
            write_to_db(data)
        time.sleep(60)  # Fetch data every minute


if __name__ == "__main__":
    run_fetcher()
