# Nuclito Resume
### Usando ChatGPT para sumarizar os posts do [Núcleo Jornalismo](https://nucleo.jor.br/)

## INSTALAÇÃO E INICIALIZAÇÃO

### Front-end 
- Docker:
```bash
docker build -t nuclito-responde-front client/
docker run -d -p 3000:3000 --rm --env-file=.env nuclito-responde-front
```
- Standalone:
```bash
cd client/
npm install
npm start
```

### Back-end
- Docker:
```bash
docker build -t nuclito-responde-back api/v2/
docker run -d -p 8000:8000 --rm --env-file=.env nuclito-responde-back
```
- Standalone:
```bash
cd api/v2/
sudo apt update
sudo apt install python3-dev \
            default-libmysqlclient-dev \
            build-essential pkg-config \
            musl \
            musl-dev \
            musl-utils \
            musl-locales
pip install -r requirements.txt
python main.py
```


## ESTRUTURA
O projeto consiste de um *client* front-end feito em [React.js](https://react.dev/) e uma API de conteúdo, para a qual foram feitas duas versões: `v1` em [Express.js](https://expressjs.com) e `v2` feita em [FastAPI](https://fastapi.tiangolo.com/). 

A versão v1 serviu como prova de conceito da aplicação e não é para ser usada em produção por gerar uma requisição à API da OpenAI toda vez que a página da aplicação é recarregada, enquanto a v2 salva os resumos gerados em um banco de dados, o que aumenta a eficiência e reduz os custos. 

A estrutura do repositório é a seguinte:
```
api/
|- v1/
|  |- Dockerfile
|  |- index.js
|  |- package.json
|- v2/
|  |- app/
|  |  |-controllers/
|  |  |-models/
|  |  |-model.py
|  |- Dockerfile
|  |- main.py
|  |- requirements.txt
client/
|- public/
|- src/
|  |- Resources/
|  |- App.js
|  |- App.css
|  |- Dockerfile
|  |- index.js
|  |- package.json
```
