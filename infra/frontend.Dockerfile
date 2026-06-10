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
# Turnstile site key (register/login bot protection). Empty = widget hidden,
# matching the backend's disabled check when its secret is unset.
ARG PUBLIC_TURNSTILE_SITE_KEY=
ENV PUBLIC_TURNSTILE_SITE_KEY=${PUBLIC_TURNSTILE_SITE_KEY}

RUN pnpm build

FROM node:20-alpine AS runtime
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.14.4 --activate
ENV NODE_ENV=production

COPY --from=builder /app/dist ./dist

# Astro output is fully static, so serve dist/ with a plain static server.
# `astro preview` (Vite) enforces a Host allowlist that's awkward behind the
# Cloudflare Tunnel; `serve` has no such check and is the right tool for static
# output. (Installed at build time, where host networking is available.)
RUN npm install -g serve@14.2.4

EXPOSE 4321
CMD ["serve", "dist", "-l", "tcp://0.0.0.0:4321"]
