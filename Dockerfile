FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Playwright's bundled node driver needs libatomic1 on slim Debian images
RUN apt-get update && apt-get install -y --no-install-recommends \
    libatomic1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for better Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + Linux system libraries required by Playwright
RUN playwright install chromium && playwright install-deps chromium

# Copy platform runtime files
COPY server.py queue_manager.py solver_engine.py ./
COPY all_42_chapters_answers.json bank_java2_54.json bank_python2_25.json ./
COPY static ./static

EXPOSE 5000

# Single worker with multiple threads keeps in-memory FIFO queue & logs unified
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 180 -b 0.0.0.0:${PORT:-5000} server:app"]
