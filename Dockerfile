FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend
WORKDIR /app/backend
ENV TRIYANA_DATABASE_URL=sqlite:////data/triyana_demo.db \
    TRIYANA_DEMO=1
RUN mkdir -p /data && useradd -m triyana && chown triyana /data
USER triyana
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
