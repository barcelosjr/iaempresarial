# Especificação de Projeto: Analista IA conectado ao Power BI

> **Como usar este documento:** abra o Claude Code na pasta onde o projeto será criado e cole a seção "PROMPT PARA O CLAUDE CODE" (Parte 2). A Parte 1 é para você entender e validar o desenho antes.

---

# PARTE 1 — Visão do Projeto (para você)

## Objetivo
Construir um "Analista IA" local que conecta o Claude aos modelos semânticos do Power BI da empresa via API REST, permitindo responder perguntas da diretoria (quantitativas e qualitativas) gastando o mínimo de tokens: o Power BI executa as consultas DAX no servidor e o Claude só interpreta os resultados resumidos.

## Princípios de arquitetura
1. **Dados brutos nunca entram no contexto do Claude** — só resultados de consultas (agregados ou recortes filtrados).
2. **Somente leitura** — o sistema jamais grava nada no Power BI.
3. **Segredos fora do código** — credenciais Azure só em `.env` (nunca commitado).
4. **Medidas oficiais primeiro** — usar as medidas já existentes no modelo semântico antes de criar cálculos próprios, garantindo consistência com os dashboards da diretoria.
5. **Complemento local** — dados que não existem no BI (planilhas avulsas, textos de pós-venda) entram num DuckDB local.

## Estrutura de pastas

```
analista-bi/
├── CLAUDE.md                      # Memória permanente do projeto p/ o Claude Code
├── README.md                      # Setup e uso para humanos
├── .env.example                   # Modelo de credenciais (o .env real fica no .gitignore)
├── .gitignore
├── requirements.txt
│
├── config/
│   ├── settings.py                # Carrega .env, valida configurações
│   └── datasets.yaml              # Workspaces e datasets mapeados (IDs + descrição)
│
├── auth/
│   └── azure_auth.py              # Autenticação Azure AD (MSAL) com cache de token
│
├── powerbi/
│   ├── client.py                  # Cliente da API: executeQueries, retry, rate limit
│   ├── schema.py                  # Descoberta do modelo: tabelas, colunas, medidas
│   └── dax_lib.py                 # Biblioteca de consultas DAX parametrizadas
│
├── mcp_server/
│   └── server.py                  # Servidor MCP local expondo ferramentas ao Claude
│
├── dictionary/
│   ├── modelo_semantico.md        # Dicionário de dados (gerado automaticamente)
│   └── regras_negocio.md          # Regras da empresa (mantido manualmente)
│
├── local_data/
│   ├── ingest.py                  # Ingestão de arquivos avulsos → DuckDB
│   └── warehouse.duckdb           # Banco local complementar (gitignored)
│
├── analysis/
│   ├── briefing_diario.py         # Análises recorrentes prontas
│   └── templates/                 # Roteiros de análises para a diretoria
│
├── reports/                       # Saídas geradas (xlsx, md, html) — gitignored
│
├── scripts/
│   ├── validar_setup.py           # Testa credenciais, permissões e conexão
│   └── gerar_dicionario.py        # Extrai o esquema do modelo → dictionary/
│
└── tests/
    ├── test_auth.py
    ├── test_client.py
    └── test_dax_lib.py
```

## Pré-requisitos (verificar ANTES de construir)
- [ ] Licença Power BI Pro (ou superior) no usuário/service principal
- [ ] Admin do tenant habilitou: **"Dataset Execute Queries REST API"** (Integration settings)
- [ ] Se usar service principal: **"Allow service principals to use Power BI APIs"** habilitado + app registrado no Azure AD com o principal adicionado ao workspace
- [ ] Usuário/principal com permissão **Read + Build** nos datasets alvo
- [ ] IDs em mãos: Tenant ID, Client ID, (Client Secret se service principal), Workspace ID(s), Dataset ID(s)
- [ ] Python 3.11+ e Claude Code instalados

---

# PARTE 2 — PROMPT PARA O CLAUDE CODE (copiar e colar)

Construa um projeto Python chamado **analista-bi** seguindo exatamente a especificação abaixo. Trabalhe em fases, validando cada uma antes de avançar. Ao final de cada fase, rode os testes e me mostre um resumo do que foi feito.

## Contexto
Sou gestor e quero que o Claude atue como analista dos dados da empresa. Os dados vivem em modelos semânticos do Power BI. Este projeto conecta o Claude ao Power BI via API REST (endpoint executeQueries com DAX), sempre somente leitura, minimizando tokens: as consultas executam no servidor do Power BI e só os resultados entram no contexto.

## Regras invioláveis
1. Nunca colocar segredos em código ou logs. Credenciais só via `.env` (python-dotenv). Criar `.env.example` documentado e incluir `.env`, `reports/`, `*.duckdb` e caches no `.gitignore`.
2. Todas as chamadas à API são somente leitura. Não implementar nenhum endpoint de escrita.
3. Toda função pública com type hints e docstring em português.
4. Tratar erros da API com mensagens claras em português indicando a causa provável (token expirado, permissão faltando, tenant setting desabilitado, rate limit).
5. Respeitar rate limits: implementar retry com backoff exponencial e limitador local de requisições por minuto (configurável, padrão conservador de 30/min).
6. Resultados de consultas limitados por padrão (TOPN) — nunca retornar dezenas de milhares de linhas para o contexto.

## FASE 1 — Fundação e autenticação
- Criar a estrutura de pastas completa (ver árvore abaixo), `requirements.txt` (msal, requests, python-dotenv, pyyaml, duckdb, pandas, openpyxl, pytest, mcp) e `README.md` com instruções de setup.
- `config/settings.py`: carrega e valida variáveis do `.env`: `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` (opcional), `AUTH_MODE` (`device_code` ou `service_principal`), `PBI_WORKSPACE_ID`, `PBI_DATASET_ID`. Falhar com mensagem clara se algo essencial faltar.
- `auth/azure_auth.py`: classe `AzureAuthenticator` com dois modos:
  - `device_code`: fluxo interativo MSAL (usuário loga com a própria conta corporativa) com cache de token em disco (`.token_cache.json`, gitignored).
  - `service_principal`: client credentials flow.
  - Método `get_token()` que renova automaticamente quando expirado. Scope: `https://analysis.windows.net/powerbi/api/.default`.
- `scripts/validar_setup.py`: testa na sequência (a) obtenção de token, (b) listagem do dataset via `GET /v1.0/myorg/groups/{workspace}/datasets/{dataset}`, (c) uma consulta DAX trivial (`EVALUATE ROW("ok", 1)`). Imprimir diagnóstico claro de cada etapa com ✅/❌ e a correção sugerida em caso de falha.
- Testes: `tests/test_auth.py` com mocks (não exigir credenciais reais para rodar pytest).

**Critério de aceite:** `python scripts/validar_setup.py` executa as 3 etapas com diagnóstico claro.

## FASE 2 — Cliente Power BI e descoberta do modelo
- `powerbi/client.py`: classe `PowerBIClient` com:
  - `execute_dax(query: str, dataset_id: str | None = None) -> pd.DataFrame` — POST em `/v1.0/myorg/groups/{workspace}/datasets/{dataset}/executeQueries`, parse do JSON de resposta para DataFrame, tratamento dos erros comuns da API, retry com backoff, respeito ao rate limit local.
  - `list_datasets() -> pd.DataFrame` e `get_dataset_info(dataset_id) -> dict`.
- `powerbi/schema.py`: funções que usam consultas DAX INFO (`INFO.TABLES()`, `INFO.COLUMNS()`, `INFO.MEASURES()`, `INFO.RELATIONSHIPS()`) para extrair o esquema do modelo. Se as funções INFO não estiverem disponíveis no dataset, degradar graciosamente e documentar a limitação no output.
- `scripts/gerar_dicionario.py`: gera `dictionary/modelo_semantico.md` com: lista de tabelas e colunas (nome, tipo, descrição se houver), lista de medidas com suas expressões DAX, relacionamentos. Este arquivo é o "mapa" que o Claude lerá antes de escrever consultas.
- `config/datasets.yaml`: estrutura para mapear múltiplos datasets com apelido, workspace_id, dataset_id e descrição de uso (ex.: `vendas`, `financeiro`, `contabil`).
- Testes: `tests/test_client.py` com respostas mockadas da API.

**Critério de aceite:** `python scripts/gerar_dicionario.py` produz um dicionário legível do modelo real.

## FASE 3 — Biblioteca DAX e servidor MCP
- `powerbi/dax_lib.py`: funções que montam consultas DAX parametrizadas e seguras (escapar aspas nos parâmetros de texto):
  - `buscar_texto(tabela, coluna, termo, limite=20)` — busca estilo "compramos cloro?" com SEARCH case-insensitive, ordenada por data desc quando houver coluna de data.
  - `ultimas_ocorrencias(tabela, coluna_data, filtros: dict, limite=20)`
  - `resumo_medidas(medidas: list[str], dimensoes: list[str] | None, filtros: dict | None)` — SUMMARIZECOLUMNS usando medidas oficiais do modelo.
  - `topn_por_medida(n, tabela_dim, coluna_dim, medida, ordem="DESC")`
- `mcp_server/server.py`: servidor MCP local (SDK `mcp`, transporte stdio) expondo as ferramentas:
  - `consultar_dax(query)` — executa DAX arbitrário (somente leitura) e retorna até N linhas.
  - `buscar_item(termo, dataset)` — atalho para busca textual.
  - `esquema_modelo(dataset)` — retorna o dicionário de dados.
  - `resumo_kpis(medidas, dimensoes, filtros)` — atalho para agregações.
  - Cada resposta de ferramenta deve incluir: linhas retornadas, total truncado (se houver) e a query executada (para auditoria).
- Documentar no README como registrar este servidor MCP no Claude Code (`claude mcp add`) e no Claude Desktop.
- Testes: `tests/test_dax_lib.py` validando a montagem correta das strings DAX (sem chamar API).

**Critério de aceite:** com o MCP registrado, consigo perguntar em linguagem natural "qual a última compra de cloro?" e o Claude usa `buscar_item`/`consultar_dax` para responder.

## FASE 4 — Complemento local e análises recorrentes
- `local_data/ingest.py`: CLI que ingere arquivos CSV/XLSX de uma pasta para tabelas no `warehouse.duckdb` (nome da tabela = nome do arquivo normalizado), com log do que foi carregado. Adicionar ao servidor MCP a ferramenta `consultar_duckdb(sql)` (somente SELECT — validar e recusar qualquer outro comando).
- `analysis/briefing_diario.py`: script que consulta os KPIs principais definidos em `analysis/templates/briefing.yaml` (faturamento do dia/mês, títulos a vencer em 7 dias, top 5 clientes do mês) e gera `reports/briefing_YYYY-MM-DD.md`. Deixar o template facilmente editável.
- `dictionary/regras_negocio.md`: criar com seções vazias comentadas para eu preencher (definições de margem, metas, sazonalidades, nomenclaturas internas).

**Critério de aceite:** `python analysis/briefing_diario.py` gera um briefing real em `reports/`.

## FASE 5 — CLAUDE.md e acabamento
- Escrever o `CLAUDE.md` do projeto instruindo o Claude (em qualquer sessão futura) a:
  1. Ler `dictionary/modelo_semantico.md` e `dictionary/regras_negocio.md` antes de escrever DAX.
  2. Preferir medidas oficiais do modelo a cálculos próprios; se criar cálculo próprio, avisar.
  3. Sempre consultar via ferramentas MCP / `PowerBIClient` — nunca pedir export de dados brutos.
  4. Em buscas textuais, tentar sinônimos e variações (ex.: cloro → hipoclorito, tricloro) antes de concluir que não existe.
  5. Ao responder a diretoria, citar o período, o filtro aplicado e a medida usada.
  6. Salvar análises formais em `reports/`.
- Revisão final: rodar pytest completo, revisar `.gitignore`, conferir que nenhum segredo aparece em código/logs, atualizar README com um guia "primeiros 15 minutos".

**Critério de aceite final:** partindo de um clone limpo + `.env` preenchido, em 15 minutos o sistema responde perguntas reais do modelo Power BI da empresa.

## Estrutura de pastas a criar

(usar exatamente a árvore da Parte 1 deste documento)

---

# PARTE 3 — Depois de construído: exemplos de uso

| Pergunta ao Claude | O que acontece por trás |
|---|---|
| "Compramos cloro? Quando foi a última vez?" | `buscar_item("cloro")` → DAX com SEARCH → 20 linhas → resposta com data, fornecedor, preço |
| "Faturamento por linha de produto vs. mesmo período do ano passado" | `resumo_kpis` com a medida oficial de faturamento + SAMEPERIODLASTYEAR |
| "Prepara o briefing de hoje para a diretoria" | roda `briefing_diario.py` e entrega o `.md` de `reports/` |
| "Esse fornecedor é confiável?" | 2–3 consultas (compras, devoluções, títulos) → parecer qualitativo |

## Custos estimados de operação
- Consulta pontual (lookup): ~1–2 mil tokens
- Análise com 3–5 consultas: ~5–15 mil tokens
- Briefing diário completo: ~10–20 mil tokens
- Os dados brutos permanecem no Power BI; só resultados resumidos trafegam.
