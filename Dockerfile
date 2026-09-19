FROM node:22-alpine AS frontend
WORKDIR /app
COPY web/package*.json ./web/
RUN cd web && npm ci
COPY web/ ./web/
COPY demo/ ./demo/
RUN cd web && npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY claimtrace/ ./claimtrace/
COPY sequitor_server.py sequitor_baseten_chain.py ./
COPY demo/ ./demo/
COPY --from=frontend /app/web/dist/ ./web/dist/
CMD ["python", "sequitor_server.py"]
