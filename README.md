# analista-bi

**Analista IA local conectado ao Power BI.** Conecta o Claude aos modelos
semânticos do Power BI da empresa via API REST (endpoint `executeQueries` com
DAX), **sempre somente leitura**, gastando o mínimo de tokens: as consultas
executam no servidor do Power BI e só os **resultados resumidos** entram no
contexto do Claude.

- 🔒 **Somente leitura** — o sistema jamais grava nada no Power BI.
- 🧮 **Tokens mínimos** — o Power BI agrega/filtra no servidor; o Claude só
  interpreta o resultado.
- 📏 **Medidas oficiais primeiro** — usa as medidas já existentes no modelo,
  garantindo consistência com os dashboards da diretoria.
- 🗃️ **Complemento local** — dados que não existem no BI (planilhas avulsas,
  textos) entram num DuckDB local.

---

## Pré-requisitos

Verifique **antes** de configurar:

- [ ] Licença **Power BI Pro** (ou superior) no usuário/service principal.
- [ ] Admin do tenant habilitou **"Dataset Execute Queries REST API"**
      (Power BI Admin Portal → Integration settings).
- [ ] Se usar **service principal**: opção **"Allow service principals to use
      Power BI APIs"** habilitada + app registrado no Azure AD com o principal
      adicionado ao workspace.
- [ ] Usuário/principal com permissão **Read + Build** nos datasets alvo.
- [ ] IDs em mãos: **Tenant ID**, **Client ID**, (**Client Secret** se service
      principal), **Workspace ID(s)**, **Dataset ID(s)**.
- [ ] **Python 3.11+** e **Claude Code** instalados.

---

## Setup

```bash
# 1. Ambiente virtual e dependências
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Credenciais
cp .env.example .env
#   Edite o .env e preencha AZURE_*, PBI_WORKSPACE_ID, PBI_DATASET_ID.
#   Escolha AUTH_MODE=device_code (login pessoal) ou service_principal.

# 3. Valide o setup (token + acesso ao dataset + consulta DAX de teste)
python scripts/validar_setup.py
```

No modo **device_code**, o `validar_setup.py` mostra uma URL e um código; abra a
URL, digite o código e faça login com sua conta corporativa. O token fica
cacheado em `.token_cache.json` (gitignored) para as próximas execuções.

---

## Primeiros 15 minutos

1. **Setup** (acima) e `python scripts/validar_setup.py` → tudo ✅.
2. **Gere o dicionário do modelo:**
   ```bash
   python scripts/gerar_dicionario.py
   ```
   Isso cria `dictionary/modelo_semantico.md` — o "mapa" que o Claude lê antes
   de escrever DAX.
3. **Preencha `dictionary/regras_negocio.md`** com suas definições (margem,
   metas, sazonalidades, sinônimos de itens).
4. **Registre o servidor MCP** no Claude Code (abaixo).
5. **Pergunte em linguagem natural**, ex.: _"Compramos cloro? Quando foi a
   última vez?"_ ou _"Prepara o briefing de hoje para a diretoria."_

---

## Registrar o servidor MCP

O servidor expõe as ferramentas de consulta ao Claude via stdio.

### Claude Code (CLI)

```bash
# A partir da raiz do projeto, com o venv ativado:
claude mcp add analista-bi -- python "$(pwd)/mcp_server/server.py"
```

> Dica: para garantir o Python do venv, use o caminho absoluto do interpretador,
> ex.: `claude mcp add analista-bi -- /caminho/analista-bi/.venv/bin/python /caminho/analista-bi/mcp_server/server.py`.

### Claude Desktop

Edite o arquivo de configuração (`claude_desktop_config.json`) e adicione:

```json
{
  "mcpServers": {
    "analista-bi": {
      "command": "/caminho/absoluto/analista-bi/.venv/bin/python",
      "args": ["/caminho/absoluto/analista-bi/mcp_server/server.py"]
    }
  }
}
```

Reinicie o Claude Desktop. As ferramentas `consultar_dax`, `buscar_item`,
`esquema_modelo`, `resumo_kpis` e `consultar_duckdb` ficarão disponíveis.

---

## Ferramentas MCP disponíveis

| Ferramenta | O que faz |
|---|---|
| `consultar_dax(query, dataset)` | Executa DAX arbitrário (somente leitura) e retorna até N linhas. |
| `buscar_item(termo, tabela, coluna, ...)` | Busca textual case-insensitive (estilo "compramos cloro?"). |
| `esquema_modelo(dataset)` | Retorna o dicionário de dados do modelo. |
| `resumo_kpis(medidas, dimensoes, filtros)` | Agregações com `SUMMARIZECOLUMNS` usando medidas oficiais. |
| `consultar_duckdb(sql)` | Consulta SELECT no banco local (complemento). |

Cada resposta inclui, para auditoria: linhas retornadas, se houve truncamento e
a query executada.

---

## Complemento local (DuckDB)

Para dados que não existem no Power BI:

```bash
# Ingere todos os CSV/XLSX de uma pasta (cada arquivo vira uma tabela)
python local_data/ingest.py /caminho/para/planilhas

# Depois consulte via ferramenta MCP consultar_duckdb (somente SELECT)
```

---

## Briefing diário

```bash
python analysis/briefing_diario.py
# Gera reports/briefing_YYYY-MM-DD.md
```

Edite os KPIs em `analysis/templates/briefing.yaml` (faturamento do dia/mês,
títulos a vencer, top clientes). **Ajuste os nomes de medidas/tabelas** para os
do seu modelo (veja o dicionário gerado).

---

## Uso diário via Claude

| Pergunta ao Claude | O que acontece por trás |
|---|---|
| "Compramos cloro? Quando foi a última vez?" | `buscar_item` → DAX com SEARCH → resposta com data, fornecedor, preço |
| "Faturamento por linha vs. mesmo período do ano passado" | `resumo_kpis` com a medida oficial + SAMEPERIODLASTYEAR |
| "Prepara o briefing de hoje" | roda `briefing_diario.py` e entrega o `.md` de `reports/` |
| "Esse fornecedor é confiável?" | 2–3 consultas (compras, devoluções, títulos) → parecer qualitativo |

---

## Testes

```bash
python -m pytest -q
```

Os testes usam **mocks** — não exigem credenciais reais nem acesso ao Power BI.

---

## Segurança

- Credenciais **apenas** no `.env` (nunca commitado — veja `.gitignore`).
- Todas as chamadas à API são **somente leitura**.
- O DuckDB local só aceita **SELECT** via `consultar_duckdb`.
- Nenhum segredo é impresso em logs ou respostas.

---

## Estrutura do projeto

```
analista-bi/
├── CLAUDE.md                 # Memória do projeto para o Claude
├── README.md                 # Este arquivo
├── .env.example              # Modelo de credenciais (.env real é gitignored)
├── requirements.txt
├── config/                   # settings.py, datasets.yaml
├── auth/                     # azure_auth.py (MSAL)
├── powerbi/                  # client.py, schema.py, dax_lib.py
├── mcp_server/               # server.py (ferramentas MCP)
├── dictionary/               # modelo_semantico.md (gerado), regras_negocio.md
├── local_data/               # ingest.py + warehouse.duckdb (gitignored)
├── analysis/                 # briefing_diario.py + templates/
├── reports/                  # saídas geradas (gitignored)
├── scripts/                  # validar_setup.py, gerar_dicionario.py
└── tests/                    # test_auth.py, test_client.py, test_dax_lib.py
```
