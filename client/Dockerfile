FROM node:18-alpine as installer

WORKDIR /app/

COPY package.json /app/
COPY public/ /app/public
COPY src/ /app/src

ENV NODE_ENV production

RUN npm install
RUN npm install -g serve


FROM installer as builder

WORKDIR /app/

ENV NODE_ENV production

ARG REACT_APP_API_URL
ARG REACT_APP_LANGUAGE

RUN npm run build
RUN MAIN_JS=$(ls build/static/js/main.*.js | cut -d'/' -f4) && ln -s $MAIN_JS build/static/js/main.js
RUN MAIN_CSS=$(ls build/static/css/main.*.css | cut -d'/' -f4) && ln -s $MAIN_CSS build/static/css/main.css

CMD ["serve", "-n", "-S", "build"]
