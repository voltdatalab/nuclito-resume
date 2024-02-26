FROM node:18-alpine

WORKDIR /app/

COPY package.json /app/package.json
COPY index.js /app/index.js

RUN npm install

EXPOSE 8080

ENV REACT_APP_GHOST_CONTENT_API=ghost_api_key
ENV REACT_APP_GHOST_CONTENT_URL=https://example.com
ENV REACT_APP_OPENAI_API_KEY=open_api_key
ENV REACT_APP_CORS_ALLOWED_ORIGINS=http://localhost

ENTRYPOINT ["node", "index.js"]
