# --- build stage -------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

# Install all deps (incl. dev) for the TypeScript build.
COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# Prune to production-only deps for the runtime image.
RUN npm ci --omit=dev

# --- runtime stage -----------------------------------------------------------
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production

# node:sqlite is built into Node 22.5+ — no native modules, nothing to compile.
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./

# PORT / DB_PATH come from fly.toml; SHARED_TOKEN comes from `fly secrets`.
EXPOSE 3000
CMD ["node", "--disable-warning=ExperimentalWarning", "dist/index.js"]
