# biblioHack — frontend container (Astro static build served by a tiny Node).
# For dev we just run `astro dev`; for prod we serve the static dist via `astro preview`
# or a static-file server. Keeping it simple here.

FROM node:20-alpine AS deps
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9.14.4 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile || pnpm install

FROM node:20-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.14.4 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./

# Astro inlines `import.meta.env.PUBLIC_*` vars at build time, so we need this
# during `pnpm build`, not just at runtime.
ARG PUBLIC_API_BASE_URL=http://localhost:8800
ENV PUBLIC_API_BASE_URL=${PUBLIC_API_BASE_URL}

RUN pnpm build

FROM node:20-alpine AS runtime
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.14.4 --activate
ENV NODE_ENV=production

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules

EXPOSE 4321
CMD ["pnpm", "preview", "--host", "0.0.0.0", "--port", "4321"]
