# CareerIQ frontend image.
#
# `development` runs the Vite dev server with HMR. `production` builds static
# assets and serves them from nginx — the React app is a static bundle, so
# shipping Node into production would be pure attack surface.

# ---------------------------------------------------------------- base
FROM node:22-alpine AS base
WORKDIR /app
ENV CI=true

# ---------------------------------------------------------------- deps
FROM base AS deps
# Copied before the source so editing a component does not invalidate the
# dependency layer.
COPY package.json package-lock.json* ./
# `npm ci` when a lockfile exists (exact, reproducible); `npm install` on the
# very first build before one has been generated.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---------------------------------------------------------------- development
FROM base AS development
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------- build
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ---------------------------------------------------------------- production
FROM nginx:1.27-alpine AS production
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
