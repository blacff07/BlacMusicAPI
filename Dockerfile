FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# --no-cache-dir keeps the image small
# The bot packages (pyrogram, pytgcalls) install fine here but aren't
# used unless you also run blacmusicbot.py inside this container.
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p downloads logs cookies

EXPOSE 8000

CMD ["python", "main.py"]
