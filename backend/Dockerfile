# Use Python 3.11 slim image as base
FROM python:3.11-slim

# Set working directory
WORKDIR /code

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY ./app ./app

# Expose port
EXPOSE 8000

# Command to run the application
CMD ["fastapi", "run", "app/main.py"]
