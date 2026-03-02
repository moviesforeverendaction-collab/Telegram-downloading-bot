FROM python:3.11-slim

WORKDIR /app

# Install build tools, ffmpeg, and aria2c
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    ffmpeg \
    aria2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
