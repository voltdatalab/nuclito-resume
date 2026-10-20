# Sincronização de resumos por publicação (opt-in)

## Fronteira, identidade e leituras

`PUBLICATION_SYNC_ENABLED=1` habilita inbox/leituras verificadas. Desligado por padrão. JSON dos GET permanece igual; catálogo novo só inclui resumos com inbox atual `done`; GET por ID sem essa prova retorna `404`, inclusive linhas legadas. Schema/DB indisponível: `503`, nunca fallback legado. Paginação nova: página não negativa, 1–100 itens. GET não gera LLM.

- HMAC-SHA256 sobre **bytes exatos do corpo + timestamp textual em ms**, janela ±300s. `X-Ghost-Signature`, fallback `X-Hook-Signature` somente com principal ausente/vazio. Segredo ausente/placeholder público `secret`: `503`. Autenticação antes de JSON. Limite real recebido 256 KiB, inclusive chunks; normalizador também limita bytes.
- Modo novo exige `event` **no JSON assinado**: `post.published`, `post.published.edited`, `post.edited`, `post.unpublished`, `post.deleted`. Ausente/desconhecido: `400`. Deleted/unpublished **sempre suprimem**, mesmo se `post.current` completo ainda declarar `published/public` (formato Ghost 6.61). Conteúdo dispensável da retirada não impede tombstone. Também aceita `current:null` + `previous.id` e `previous.deleted_at`/`updated_at`; não inventa ordem pelo recebimento.
- ID: 24 hex minúsculos. Datas UTC canônicas `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` (ou offset UTC `+00:00`, normalizado para o mesmo watermark). URL HTTPS canônica `nucleo.jor.br`/`www.nucleo.jor.br`, caminho terminado em `/`, sem credenciais, porta explícita, query, fragmento, escapes, controles ou segmentos de navegação. Título ≤1000 caracteres, plaintext/HTML ≤200000 cada; plaintext não vazio para publicar. Corpo >256 KiB rejeitado independentemente de elegibilidade.
- Só `status=published` **e** `visibility=public`, tags estruturalmente válidas; tag primária nula válida. **Diferença intencional do RAG:** resumos mantêm exclusão legada de tag primária terminada em `news`; RAG pode aceitar newsletter pública. Não é divergência de autenticação/retirada. Supressão persiste só identidade/watermark/elegibilidade/digest e URL canônica de origem verificada, nunca título/texto. Tombstone sem URL só é admitido para ID com evidência local persistida; conserva essa URL para que uma troca acidental de configuração não perca a prova de origem.
- POST: `204` após commit durável; `401` assinatura inválida; `400` envelope/campos; `409` conflito público na mesma revisão; `413` excesso; `503` segredo/schema/DB. Logs/erros não incluem corpo, assinatura, credenciais ou SQL. SQL echo desativado/parâmetros ocultados.

## Origem confiável e isolamento de staging

`PUBLICATION_SOURCE_ORIGIN` tem apenas dois valores configuráveis exatos: `https://nucleo.jor.br` (default quando ausente) ou `https://staging.nucleo.jor.br` (opt-in exclusivo). Não aceita barra final, portas, userinfo, sufixos, query/fragmento nem `www` como valor de configuração. Produção continua aceitando o alias legado `https://www.nucleo.jor.br` nas URLs de artigos e na Admin API; staging **não** aceita esse alias, `www.staging`, produção ou outros hosts.

A mesma política protege normalização, páginas/IDs do reconciliador, host TLS/DNS do fetch, jobs persistidos antes da geração, adapter, finish e leituras verificadas. URLs presentes nas retiradas também são validadas, inclusive `previous.url`; tombstones sem URL exigem prova local do ID no banco, além do segredo HMAC **distinto por ambiente**. Enqueue/upsert, claim (antes de token/lease/tentativas), expiração, finish e fail validam as URLs conhecidas da inbox e do post dentro da transação; conflito rejeita sem mutar o alvo. O cursor sem namespace exige uma inspeção local das URLs persistidas antes de criação/avanço e aborta em banco de origem conhecida incompatível; essa inspeção de segurança percorre o banco e não está limitada pelo orçamento de chamadas CMS. Não classifica registros históricos sem origem conhecida nem torna bancos compartilhados seguros. URLs de posts nunca escolhem destino de fetch. Origem Admin deve pertencer ao ambiente selecionado, mantendo chave Admin só em ambiente. CLI valida origem/chave antes de importar engine; no-op continua sem I/O.

Com `PUBLICATION_SOURCE_ORIGIN` explícita, CORS é limitado às origens do ambiente (produção + alias legado ou apenas staging), ignorando `CORS_ALLOWED_ORIGINS=*`. Sem essa variável, CORS legado permanece inalterado. **Compatibilidade explícita:** com sync OFF e variável ausente, o contrato antigo de URLs arbitrárias permanece, exceto staging bloqueado; configurar a variável torna também esse ingresso estrito. Homologação deve usar sync ON; modo OFF continua tendo GET legado e não oferece isolamento de dados de um banco indevidamente compartilhado. Bancos, credenciais, segredos e volumes separados são pré-requisitos, não substituídos por esta política.

Configuração pública proposta para o serviço isolado, sem executá-la:

```sh
export PUBLICATION_SOURCE_ORIGIN=https://staging.nucleo.jor.br
export PUBLICATION_GHOST_ADMIN_ORIGIN=https://staging.nucleo.jor.br
export PUBLICATION_SYNC_ENABLED=1
export CORS_ALLOWED_ORIGINS=https://staging.nucleo.jor.br
# WEBHOOK_SECRET e PUBLICATION_GHOST_ADMIN_KEY: provisionar separados, nunca copiar produção.
python -m app.publication_cli reconcile --apply --pages 1 --known 1 --page-size 1
python -m app.publication_cli worker --run --once
```

`--once` limita a um claim, não a uma chamada LLM (o adapter pode fazer três); requer aprovação de custo para execução real. Não instalar worker/cron nem usar loop ilimitado nesta rodada. Alteração de ambiente exige reiniciar por rota autorizada para reconstruir o middleware CORS; não trocar origem de um processo ativo ou reaproveitar banco de outro ambiente.

## Watermark, geração e data pública

Watermark = `updated_at` em microssegundos UTC. Cada ID guarda última revisão, não histórico. Digest inclui elegibilidade/título/URL/plaintext e `published_at` disponível, **não** watermark. Evento antigo não retrocede; duplicata não regenera. Supressão vence empate; replay público empatado não ressuscita. Publicação estritamente posterior pode recriar.

Edição com digest diferente e toda retirada removem resumo pronto **na transação do enqueue**. Durante pending/supressão: ID `404`, catálogo sem item. Worker não é necessário para esconder conteúdo antigo. Revisão mais nova com digest idêntico conserva token/lease/tentativas/estado e avança watermark/payload. Finish/fail validam **token + digest + processing**, não revisão antiga do claim; até a quinta tentativa válida termina sem virar dead por avanço apenas de watermark. Reclaim/conteúdo diferente invalidam o token anterior.

Data pública = `published_at`, separada do watermark. Compatibilidade explícita para fixtures/fontes antigas sem esse campo: usa `updated_at` como substituta, sem afirmar data original desconhecida. Ghost deve fornecer `published_at` no fluxo normal. Alterar data publicada altera digest/projeção.

Worker: claim atômico, lease 120s, até cinco claims por conteúdo (crashes incluídos); backoff desde falha 10/20/40/80s, teto 3600s. Última tentativa expirada vira `dead`; duplicata não reseta. Geração fora da transação; três strings PT, três EN e título EN não vazio antes do commit fenced. Adapter faz três chamadas, timeout SDK 30s/retries SDK zero, uma tentativa por claim. Crash após chamada pode repetir custo: **não há exactly-once LLM**. Nenhuma geração real feita na validação.

## Reconciliação periódica limitada e retomável

CLI faz uma fatia por execução, para agendamento operacional externo após autorização. **Não instala cron/supervisor.** Usa o mesmo `normalize` + `Inbox.enqueue` do webhook; reconciliação não gera resumos.

- Ghost Admin API por JWT HS256, audience `/admin/`, validade 5min. `PUBLICATION_GHOST_ADMIN_ORIGIN`: produção aceita exatamente `https://nucleo.jor.br` ou `https://www.nucleo.jor.br`; opt-in staging aceita só `https://staging.nucleo.jor.br`. `PUBLICATION_GHOST_ADMIN_KEY`: só ambiente, nunca argumento/relatório. Content API pública não decide privacidade.
- HTTPS com CAs do sistema/verificação de hostname. DNS: todas as respostas precisam ser IPs globais; socket fixa endereço validado, preservando SNI/hostname original, sem segunda resolução. Sem redirects, proxies, `.netrc` ou URLs derivadas de posts. Timeout socket 10s; resposta ≤2 MiB. 401/403/429/5xx, TLS, JSON inválido e timeout são falhas, **não deleções**.
- `publication_reconcile_cursor` persiste página Admin e watermark de IDs conhecidos independentes, com CAS de versão. Páginas ordenadas por ID, `filter=status:[published,draft,scheduled,sent]`, tags e plaintext/HTML. Cicla à primeira página no fim. Offset pode se deslocar durante mudanças no CMS; ciclos repetidos e sondas individuais corrigem isso, sem promessa de snapshot global.
- GET autoritativo dos IDs da **união `posts` legados + inbox**, em lotes keyset cíclicos. Não se limita a IDs já admitidos na inbox. IDs legados não-Ghost são pulados e ocultos no modo novo. Legados públicos válidos entram no mesmo fluxo e só aparecem após geração nova; resumo antigo não é considerado verificado.
- Ausência de página parcial **nunca apaga**. Só GET individual autenticado `404` suprime no watermark conhecido (zero para legado sem watermark), com comparação do estado capturado **antes** do GET para não sobrescrever webhook concorrente. Stale não reverte; tombstone bloqueia replay empatado; worker antigo não ressuscita.
- Por execução: `--pages` 1–10, `--known` 1–100, `--page-size` 1–100; defaults 1/20/20. Até páginas×page-size normalizações e `known` sondas. Reduzir page-size se artigos grandes excederem 2 MiB. Frequência/tamanhos dos ciclos determinam freshness: medir cobertura/falhas antes de prometer SLA. Falha não avança cursor; itens anteriores podem ter commit e são seguros de repetir. Evitar sobreposição; CAS protege avanço, não elimina chamadas externas duplicadas.

## Schema, uso e ativação — autorização remota separada

`publication_inbox` (LONGTEXT MySQL, índice de jobs devidos) e `publication_reconcile_cursor` são InnoDB, **fora do metadata legado**. Runtime não cria tabelas/migra `posts`. Provisionamento explícito idempotente só cria novas tabelas; schema existente incompatível exige revisão/migração própria. Confirmar `posts` InnoDB/PK id/encoding compatíveis e backup/restauração antes de produção.

A partir de `api/v2`, comandos propostos, **não executados remotamente**:

```sh
python -m app.publication_cli schema                 # no-op, nem importa engine
python -m app.publication_cli schema --apply         # ÚNICO caminho DDL novo
python -m app.publication_cli worker --run --once    # exige flag =1
python -m app.publication_cli worker --run           # loop foreground, exige flag =1
python -m app.publication_cli reconcile              # no-op, ZERO DB/CMS I/O
python -m app.publication_cli reconcile --apply --pages 1 --known 20 --page-size 20
# último exige flag =1 + env Admin origin/key; não faz chamadas LLM
```

Agendador autorizado deve invocar periodicamente a última forma, serializado, e observar exit status/contagens agregadas. Worker separado. Antes de ativar: testar MySQL 8 descartável (locks/concorrência/rollback), confirmar entrega/Admin API Ghost 6.61 com autorização, provisionar schema, reconciliar baseline, ativar entregas independentes para resumos/RAG. Não presumir webhook/cron já ativo. Manter UI tolerante a pending/404 e sem reaproveitar resumo antigo.

Flag desligada preserva GET/catalogação legado e POST síncrono `controller.create`, sem atualizar IDs existentes. Compatibilidade de ID/URL/revisão ausente existe **só** em `require_revision=False` desse modo; HMAC bruto, limites, visibilidade e override de retirada continuam. Modo desligado não oferece ordenação/reconciliação nem retirada de resumos legados já persistidos.

## Validação offline e limites

```sh
# raiz do repo; venvs privados (instalar requirements-test.txt somente neles)
"$HOME/.hermes/profiles/nuclito/cache/scratch/summary-sync-py310/bin/python" -m pytest -q
"$HOME/.hermes/profiles/nuclito/cache/scratch/summary-sync-venv/bin/python" -m pytest -q
```

SQLite descartável + SQLAlchemy e app HTTP reais; sockets bloqueados. Fixtures sintéticas com event assinado, published_at, HTML/plaintext e tag primária nula. Testes cobrem quinta tentativa/fence, leitura legada fail-closed, cursor/restart/ciclo, página parcial/404 concorrente/stale/erro de origem, SSRF/TLS/redirects e opt-in/schema. **OpenAI SDK 3.35.1 real + MockTransport em processo** exercita o adapter PT/EN, sem provar modelo servido ou disponibilidade OpenAI. DDL MySQL compilado, **runtime MySQL 8 não testado**: cliente local existe, servidor/fixture descartável não disponível. Nenhum acesso CMS/DB produtivo, volume, deploy, commit ou push.

## Rollback

Quiescer entregas; parar workers/reconciliador antes de trocar modo. Não concorrer com escrita legada. Preservar inbox/cursor/tombstones/DB; nunca dropar tabela/restaurar resumo antigo/apagar watermark como rollback. Flag desligada volta ao legado sem garantias novas; se privacidade/revisão forem necessárias, preferir receiver fail-closed/worker pausado até correção. Reativação reutiliza claims; monitorar dead/atrasos/ciclos sem conteúdo em logs. Payload público durável permanece na última linha até substituição/supressão; retenção/limpeza é decisão operacional separada.
