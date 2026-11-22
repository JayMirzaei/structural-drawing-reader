# The Streamlit app (default) and the drawing-reader command line, in one image.
#
#   docker build -t drawing-reader .                       # rules + all hosted-provider SDKs
#   docker build -t drawing-reader --build-arg OCR=1 .     # also the OCR path for scanned PDFs
#   docker run --rm -p 8501:8501 drawing-reader            # app on http://localhost:8501
#   docker run --rm drawing-reader drawing-reader eval     # acceptance questions, rules only
#
# Provider keys come from the environment, e.g. --env-file .env (see .env.example). Without one the
# reader answers from its rules alone. The app has no login: with a key set, anyone who can reach the
# port can spend it, so publish the port on 127.0.0.1 (as docker-compose.yml does) unless the network
# is trusted. Not built on the machine this was written on; CI builds it.

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv

# 1 adds the OCR extra (rapidocr + onnxruntime + OpenCV, about 200 MB more) and the two system
# libraries OpenCV loads at import.
ARG OCR=0

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DRAWING_READER_CACHE=/data/cache

RUN if [ "$OCR" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app

# Dependencies first, so a source change does not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN extras="--extra gemini --extra openai --extra anthropic"; \
    if [ "$OCR" = "1" ]; then extras="$extras --extra ocr"; fi; \
    uv sync --frozen --no-dev --no-install-project $extras

COPY src ./src
COPY app ./app
COPY eval ./eval
COPY examples ./examples
COPY .streamlit/config.toml ./.streamlit/config.toml
RUN extras="--extra gemini --extra openai --extra anthropic"; \
    if [ "$OCR" = "1" ]; then extras="$extras --extra ocr"; fi; \
    uv sync --frozen --no-dev --no-editable $extras

RUN useradd --create-home --uid 1000 reader \
    && mkdir -p /data/cache \
    && chown -R reader /app /data
USER reader
VOLUME /data

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')"

CMD ["streamlit", "run", "app/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
