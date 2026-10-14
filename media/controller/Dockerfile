FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends util-linux ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY media/controller/package*.json ./
RUN npm ci --omit=dev --ignore-scripts
COPY media/controller/*.mjs media/controller/bootstrap.py ./
CMD ["flock", "-n", "-E", "0", "/state/recap-controller.lock", "node", "main.mjs"]
