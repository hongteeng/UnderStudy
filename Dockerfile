FROM node:22-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY web/package*.json web/
RUN cd web && npm ci
COPY . .
RUN cd web && npm run build
ENV HOST=0.0.0.0 PORT=7860
EXPOSE 7860
CMD ["node", "web/dist/server.js"]
