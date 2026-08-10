FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY . /app
RUN python -m pip install --no-cache-dir .

RUN addgroup --system labarchive \
    && adduser --system --ingroup labarchive labarchive \
    && mkdir -p /data/labarchive/media \
    && chown -R labarchive:labarchive /data/labarchive /app

USER labarchive

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
