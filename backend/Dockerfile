FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels ".[postgres,telegram]"

FROM base AS runtime
RUN useradd --create-home --uid 10001 docmind
COPY --from=build /wheels /wheels
RUN pip install /wheels/*.whl && rm -rf /wheels
USER docmind
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)"
CMD ["uvicorn", "docmind.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
