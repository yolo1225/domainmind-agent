FROM node:18.20-alpine

WORKDIR /app/frontend

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

HEALTHCHECK --interval=10s --timeout=5s --retries=12 CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:5173/"]

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
