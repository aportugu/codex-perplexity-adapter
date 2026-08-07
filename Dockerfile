FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY codex_perplexity_adapter ./codex_perplexity_adapter
RUN pip install --no-cache-dir .

EXPOSE 4000
CMD ["codex-perplexity-adapter", "--host", "0.0.0.0", "--port", "4000"]
