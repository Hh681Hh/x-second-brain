FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY xsecondbrain ./xsecondbrain
RUN pip install --no-cache-dir ".[semantic]"
ENV HOST=0.0.0.0 PORT=8787 DATA_DIR=/data LLM_PROVIDER=api
EXPOSE 8787
# APP_TOKEN is required for non-loopback listening. Supply it at runtime.
CMD ["python", "-m", "xsecondbrain.main"]
