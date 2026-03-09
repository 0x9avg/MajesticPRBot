FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/prmajestic

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

COPY services/twitch_bot/requirements.txt services/twitch_bot/requirements.txt
COPY VERSION VERSION

RUN pip install --upgrade pip \
    && pip install -r services/twitch_bot/requirements.txt

COPY services/twitch_bot services/twitch_bot

RUN mkdir -p /opt/prmajestic/logs /opt/prmajestic/state/twitch \
    && chown -R app:app /opt/prmajestic

USER app
WORKDIR /opt/prmajestic/services/twitch_bot

CMD ["python", "main.py"]
