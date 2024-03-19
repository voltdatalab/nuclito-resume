### Versão 1.0 (prova de conceito em javascript)

A versão 1.0 foi criada em javascript como forma de acelerar a prova de conceito da aplicação e não deve ser utilizada em produção, apenas em testes internos limitados, com cachê.

Leve em conta que, sob a versão 1.0, toda vez que a aplicação é recarregada ela incorre em um novo request para a API da OpenAI, o que gera novos custos.

Para uso em produção, use a versão 2.0.

## REQUISITOS

* Token da OpenAI
* Token de conteúdo do Ghost
* Frontend servido em React
* Backend servido em Express

## DEPENDÊNCIAS

#### INSTALA EXPRESS (para rodar APP) e NODE-FETCH (para reguisições)
`npm install express node-fetch`

#### INSTALA API GHOST
`npm install @tryghost/content-api`

#### INSTALA OPENAI
`npm install openai`

### PACOTE PARA DEPENDENCIAS
`npm install dotenv`

#### COMANDO ÚNICO
`npm install npm express node-fetch @tryghost/content-api openai dotenv`

## INICIALIZAÇÃO

Após incluídas as variáveis de ambiente:

* /server: `node index.js`
* /client: `npm run start`
