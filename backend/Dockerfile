FROM python:3.11-slim

WORKDIR /app

# System dependencies (none needed beyond slim base for xknx)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Data volume mount point
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
