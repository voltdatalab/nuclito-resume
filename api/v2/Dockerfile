FROM python:3.10-alpine

WORKDIR /app
COPY . .

RUN apk update \
    && apk add --virtual build-deps gcc python3-dev musl-dev \
    && apk add --no-cache mariadb-dev musl musl-utils musl-locales

RUN cp /usr/share/zoneinfo/America/Sao_Paulo /etc/localtime
RUN echo "America/Sao_Paulo" > /etc/timezone

ENV TZ America/Sao_Paulo
ENV LANG pt_BR.UTF-8
ENV LANGUAGE pt_BR.UTF-8
ENV LC_ALL pt_BR.UTF-8
ENV MUSL_LOCPATH /usr/share/i18n/locales/musl
    
RUN pip install -r /app/requirements.txt

RUN apk del build-deps

ENV APP_NAME "nuclito-responde.api.v2"
ENV WEBHOOK_SECRET "secret"
ENV DB_ENGINE "mysql"
ENV DB_HOST "0.0.0.0"
ENV DB_PORT 3306
ENV DB_DATABASE "database"
ENV DB_USERNAME "user"
ENV DB_PASSWORD "password"
ENV OPENAI_API_KEY "apikey"
ENV CORS_ALLOWED_ORIGINS "*"
ENV API_HOST "0.0.0.0"
ENV API_PORT "8000"

EXPOSE 8000

CMD python /app/main.py
