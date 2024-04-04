FROM node:18-alpine

WORKDIR /app/

COPY public/ /app/public
COPY src/ /app/src
COPY package.json /app/

ENV NODE_ENV production

RUN npm install
RUN npm install -g serve

ENV REACT_APP_API_URL http://localhost:8080
ENV REACT_APP_LANGUAGE pt_BR

RUN npm run build:dist

CMD ["serve", "-p", "80", "dist"]
