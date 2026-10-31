# Built with the repository root as context so that only apps/notebook and research/ are copied.
FROM node:22-alpine AS deps
WORKDIR /repo/apps/notebook
COPY apps/notebook/package.json apps/notebook/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /repo/apps/notebook
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /repo/apps/notebook/node_modules ./node_modules
COPY apps/notebook/ ./
COPY research/ /repo/research/
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3100
COPY --from=build /repo/apps/notebook/.next/standalone ./
COPY --from=build /repo/apps/notebook/.next/static ./.next/static
COPY --from=build /repo/apps/notebook/public ./public
USER node
EXPOSE 3100
CMD ["node", "server.js"]
