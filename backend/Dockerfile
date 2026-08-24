FROM python:3.12-slim

# Install Tesseract OCR engine (system package, not a pip package)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render sets $PORT at runtime; gunicorn binds to it
RUN pip install --no-cache-dir gunicorn
CMD gunicorn --bind 0.0.0.0:$PORT --timeout 120 app:app
