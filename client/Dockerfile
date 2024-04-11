FROM node:18-alpine

WORKDIR /app/

COPY public/ /app/public
COPY src/ /app/src
COPY package.json /app/

ENV NODE_ENV production

RUN npm install
RUN npm install -g serve

ARG REACT_APP_API_URL
ARG REACT_APP_LANGUAGE

RUN npm run build
RUN MAIN_JS=$(ls build/static/js/main.*.js | cut -d'/' -f4) && ln -s $MAIN_JS build/static/js/main.js
RUN MAIN_CSS=$(ls build/static/css/main.*.css | cut -d'/' -f4) && ln -s $MAIN_CSS build/static/css/main.css

CMD ["serve", "-n", "-S", "build"]
