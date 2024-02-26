FROM node:18-alpine

WORKDIR /app/

COPY public/ /app/public
COPY src/ /app/src
COPY package.json /app/

RUN npm install

ENV REACT_APP_API_URL=http://localhost:8080

EXPOSE 3000

CMD ["npm", "run", "start"]
