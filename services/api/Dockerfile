FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/prmajestic

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

COPY services/api/requirements.txt services/api/requirements.txt
COPY VERSION VERSION

RUN pip install --upgrade pip \
    && pip install -r services/api/requirements.txt

COPY services/api services/api

RUN mkdir -p /opt/prmajestic/logs \
    && chown -R app:app /opt/prmajestic

USER app
WORKDIR /opt/prmajestic/services/api

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
