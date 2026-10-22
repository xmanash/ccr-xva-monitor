FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY data ./data
COPY scripts ./scripts
COPY docs ./docs
RUN pip install --no-cache-dir .

COPY docker/start.sh /start.sh
RUN chmod +x /start.sh

ENV PYTHONPATH=/app/src
ENV CCR_ROOT=/app
ENV CCR_DATABASE_URL=sqlite:////app/data/ccr_xva.db
ENV CCR_CHROMA_PATH=/app/data/chroma
EXPOSE 8000 8501
CMD ["/start.sh"]
