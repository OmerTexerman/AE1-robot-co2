FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/lib/python3/dist-packages

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg build-essential curl python3-louis \
       libharfbuzz-dev libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--timeout", "300", "app:app"]
