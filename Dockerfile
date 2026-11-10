FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# No browser needed — the scraper talks to ImmoScout24's app API and immobilienscout24.at's JSON over plain HTTP with a real Chrome TLS fingerprint.
CMD ["python", "run.py"]
