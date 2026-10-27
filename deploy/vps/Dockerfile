FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JARVIS_ENV=production \
    PORT=8000

WORKDIR /app
COPY backend-cloud/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --system --create-home --uid 10001 jarvis
COPY backend-cloud/ ./
RUN mkdir -p /var/lib/jarvis && chown -R jarvis:jarvis /app /var/lib/jarvis
ENV JARVIS_DATA_DIR=/var/lib/jarvis
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
