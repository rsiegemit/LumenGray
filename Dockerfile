# Portable container for LumenGray — works on Fly.io, Hugging Face Spaces,
# Railway, Cloud Run, or any Docker host. Serves on $PORT (default 8000).
FROM python:3.13-slim

# trimesh/scipy/numpy wheels are self-contained; no system build deps needed.
WORKDIR /app
COPY pyproject.toml ./
COPY lumengray ./lumengray
RUN pip install --no-cache-dir ".[web]"

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn lumengray.web.server:app --host 0.0.0.0 --port ${PORT}"]
