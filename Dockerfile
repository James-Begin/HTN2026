FROM node:22-alpine AS frontend
WORKDIR /app
COPY web/package*.json ./web/
# The checked-in lockfile records a developer-only registry. Railway must build
# from the public registry without rewriting that local artifact.
RUN cd web && npm install --package-lock=false --ignore-scripts --registry=https://registry.npmjs.org/
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
