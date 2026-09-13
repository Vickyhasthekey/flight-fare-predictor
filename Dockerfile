FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api ./api
COPY src ./src
COPY models ./models
COPY artifacts ./artifacts

RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "api.predict:app", "--host", "0.0.0.0", "--port", "8000"]
