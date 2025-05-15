FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Environment variables will be set when running the container
ENV MQTT_TOPICS="[]"
ENV SERVICE_ID=""

# Command to run the monitoring service
CMD ["python", "app.py"]