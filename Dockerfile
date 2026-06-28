FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app

EXPOSE 8091

HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD python -c "import json, urllib.request; json.load(urllib.request.urlopen('http://127.0.0.1:8091/health', timeout=2))"

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091"]
