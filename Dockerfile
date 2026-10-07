FROM python:3.14-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151 AS dependencies

ENV PIPENV_DONT_LOAD_ENV=1
WORKDIR /build
COPY Pipfile Pipfile.lock ./
RUN python -m pip install --no-cache-dir pipenv==2024.0.1 \
    && pipenv requirements --hash > /tmp/requirements.txt \
    && python -m pip install --no-cache-dir --require-hashes --ignore-installed --prefix=/install \
       -r /tmp/requirements.txt

FROM python:3.14-slim@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY --from=dependencies /install /usr/local
COPY main.py database.py alembic.ini ./
COPY config ./config
COPY controllers ./controllers
COPY dependencies ./dependencies
COPY models ./models
COPY serializers ./serializers
COPY services ./services
COPY migrations ./migrations
COPY data/sports_data.py ./data/sports_data.py
COPY scripts/import_sports.py ./scripts/import_sports.py

USER 10001:10001
EXPOSE 8000
CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1 --proxy-headers --forwarded-allow-ips=\"*\""]
