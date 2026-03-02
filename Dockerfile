FROM python:3.11-slim

WORKDIR /app

# Install gcc for building tgcrypto if a pre-compiled wheel isn't available
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Start the bot
CMD ["python", "bot.py"]
