# Pukaar Lambda images. Build context: the repository root (backend/ and data/).
#   target api    -> FastAPI behind the Lambda Web Adapter (Lambda `api`)
#   target worker -> plain handlers via awslambdaric (Lambdas `sweep`, `workflow`, `worker`;
#                    the function's ImageConfig.Command picks the handler)
# Local run:  docker build -f backend/Dockerfile --target api -t pukaar-api .

FROM python:3.12-slim AS build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /src
# Dependencies first so code edits do not invalidate this layer.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    PUKAAR_DATA_DIR=/var/task/data
COPY --from=build /opt/venv /opt/venv
COPY data /var/task/data
WORKDIR /var/task

FROM base AS api
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/health
EXPOSE 8080
CMD ["uvicorn", "Pukaar.main:app", "--host", "0.0.0.0", "--port", "8080"]

FROM base AS worker
RUN pip install --no-cache-dir --target /opt/ric awslambdaric==3.1.1
ENV PYTHONPATH=/opt/ric
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["Pukaar.handlers.worker.handler"]
