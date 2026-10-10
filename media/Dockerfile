FROM mcr.microsoft.com/playwright:v1.64.0-noble@sha256:06a9939e57531807f8d5fd76ce44b53165ffb7d7501d87ab10e285c20b1e971f
ARG VCS_REF=unrecorded
LABEL org.opencontainers.image.revision=$VCS_REF
ENV DEBIAN_FRONTEND=noninteractive PYTHONPATH=/opt/recap:/opt/recap/api:/opt/recap/src PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg=7:6.1.1-3ubuntu5 bubblewrap=0.9.0-1ubuntu0.3 python3-venv time && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
WORKDIR /opt/recap
COPY media/requirements.lock media/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir -r media/requirements.lock
COPY media/package*.json media/
RUN cd media && npm ci
COPY media media
COPY api/app/services/recap_video/audio.py api/app/services/recap_video/audio.py
COPY api/app/services/recap_video/elevenlabs.py api/app/services/recap_video/elevenlabs.py
COPY scripts/check_recap_media_runtime.py scripts/check_recap_media_runtime.py
COPY scripts/benchmark_recap_media.py scripts/benchmark_recap_media.py
COPY api/tests/test_recap_render_contract.py api/tests/test_recap_render_contract.py
COPY api/tests/fixtures/recap_media api/tests/fixtures/recap_media
ENV PATH=/opt/venv/bin:/usr/bin:/bin
CMD ["python", "-m", "media.worker"]
