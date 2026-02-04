FROM python:3.12-slim

WORKDIR /app

# System dependencies for PostgreSQL client, browser automation, and general tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    wget \
    gnupg \
    # Browser dependencies
    libgtk-3-0 \
    libdbus-glib-1-2 \
    libxt6 \
    libasound2 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libnspr4 \
    libnss3 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Patchright browser
RUN pip install --no-cache-dir --no-deps patchright && \
    patchright install-deps chromium && \
    patchright install chromium

# Application code
COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

# Data directory (TEA DB will be mounted here)
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
