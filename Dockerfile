FROM python:3.13-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl unzip ca-certificates xz-utils tini \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:${PATH}"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY pyproject.toml ./
COPY README.md ./
COPY LICENSE ./
COPY src ./src
COPY app.py ./

RUN pip install --no-cache-dir .[gcloud]

RUN git clone -b tg-load --single-branch --depth 1 https://github.com/denyshon/python-youtube-music /tmp/ytmusic \
 && pip install --no-cache-dir "/tmp/ytmusic[dl]" \
 && rm -rf /tmp/ytmusic

RUN apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

ARG FFMPEG_URL=https://github.com/yt-dlp/FFmpeg-Builds/releases/download/autobuild-2025-12-08-14-18/ffmpeg-N-122031-gc4d22f2d2c-linux64-gpl.tar.xz
ARG FFMPEG_BIN_DIR=/opt/tools
ENV FFMPEG_LOCATION=${FFMPEG_BIN_DIR}

RUN mkdir -p ffmpeg \
 && curl -fsSL "${FFMPEG_URL}" -o /tmp/ffmpeg.tar.xz \
 && tar -xf /tmp/ffmpeg.tar.xz -C ffmpeg --strip-components=1 \
 && mv ffmpeg/bin/ ${FFMPEG_BIN_DIR}/ \
 && rm -f /tmp/ffmpeg.tar.xz \
 && chmod +x ${FFMPEG_BIN_DIR}/*

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]