FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy AS runtime

WORKDIR /app
COPY --from=builder /install /usr/local
COPY src ./src

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
