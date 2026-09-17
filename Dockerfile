FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api ./api
COPY src ./src
COPY models ./models
COPY artifacts ./artifacts
COPY public ./public

RUN pip install --no-cache-dir .

# Optional: pass -e SERPAPI_API_KEY=... so Find flights can call Google Flights.
# /health and POST /api/predict still work without it.
EXPOSE 8000
CMD ["uvicorn", "api.predict:app", "--host", "0.0.0.0", "--port", "8000"]
