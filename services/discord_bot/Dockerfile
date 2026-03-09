FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/prmajestic

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

COPY services/discord_bot/requirements.txt services/discord_bot/requirements.txt
COPY VERSION VERSION

RUN pip install --upgrade pip \
    && pip install -r services/discord_bot/requirements.txt

COPY services/discord_bot services/discord_bot

RUN mkdir -p /opt/prmajestic/logs \
    && chown -R app:app /opt/prmajestic

USER app
WORKDIR /opt/prmajestic/services/discord_bot

CMD ["python", "main.py"]
