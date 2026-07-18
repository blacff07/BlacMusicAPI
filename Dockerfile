FROM python:3.12-slim

WORKDIR /app

# Unbuffered stdout — without this, Python batches log output in a container
# and platforms like Railway/Render can appear to show "no logs" for a long
# time even though the app is working correctly.
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN apt-get update -y \
    && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates gnupg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp solves YouTube's n-signature challenge with a JS runtime. Without
# Node >= 23.5 present, cookieless resolution silently degrades to
# "Sign in to confirm you're not a bot" — Node MUST be in the image.
RUN curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && node --version

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs

ENV PORT=7860
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["python", "main.py"]
