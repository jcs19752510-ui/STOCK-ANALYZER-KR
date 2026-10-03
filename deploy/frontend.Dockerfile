# Frontend image (Next.js). NEXT_PUBLIC_* values are baked into the browser bundle at BUILD time,
# so they are build args here. Changing them later requires a rebuild.
# Build from the repo root:  docker build -f deploy/frontend.Dockerfile --build-arg NEXT_PUBLIC_API_BASE_URL=https://example .
FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./

ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED=false
ARG NEXT_PUBLIC_PATTERN_SCREEN_ENABLED=true
# Intentionally NOT set: NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED (personal local mode must stay off in public deployments).
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED=${NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED} \
    NEXT_PUBLIC_PATTERN_SCREEN_ENABLED=${NEXT_PUBLIC_PATTERN_SCREEN_ENABLED}
RUN test -n "$NEXT_PUBLIC_API_BASE_URL" || (echo "NEXT_PUBLIC_API_BASE_URL build arg is required" && exit 1)
RUN npm run build

FROM node:22-bookworm-slim
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=build /app/package.json /app/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.mjs ./
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-H", "0.0.0.0", "-p", "3000"]
