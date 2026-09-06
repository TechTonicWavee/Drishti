# Frontend — development image.
#
# Dev mode only: it runs the Vite dev server so edits on the host are picked up
# live. A production image would `npm run build` and serve dist/ from a static
# server; that is deliberately out of scope for this scaffold.
FROM node:24-slim

WORKDIR /app

# Dependencies are installed at image-build time. Once the image exists, the
# running container needs no registry access — matching the air-gapped target.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0 so the published port is reachable from the host.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
