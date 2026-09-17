# Migração do Claude Code para outro notebook — Grupo Mult / Controladoria

> Levantado em **17/09/2026** a partir do notebook atual (usuário Windows
> `Controladoria`, Windows 11). Este arquivo esquematiza **tudo o que foi feito
> com o Claude Code nesta máquina** e o que precisa ser copiado, reinstalado ou
> reconfigurado para recomeçar em outro computador sem perder nada.

---

## 0. Resumo executivo (leia isto primeiro)

| # | O que | Situação hoje | Ação na migração |
|---|---|---|---|
| 1 | **Projeto principal `iaempresarial`** (analista-bi: Power BI + MCP + painéis + COAF + conciliação) | Repositório GitHub `barcelosjr/iaempresarial`, mas com **70 alterações locais não commitadas** (16 arquivos modificados + ~54 novos). O último push foi em 31/08/2026. | **Commitar e dar push ANTES de tudo** (seção 2.1). Sem isso, COAF, conciliação de caixa, planilhas e painéis por revenda se perdem. |
| 2 | Arquivos **fora do git** do `iaempresarial` (`.env`, `warehouse.duckdb`, `reports/`, `logs/`) | Só existem nesta máquina | Copiar manualmente por pendrive/OneDrive (seção 2.2). O DuckDB guarda o **histórico permanente do COAF** — não pode ser recriado. |
| 3 | **Tarefas agendadas do Windows** (COAF, a cada 30 min, **com envio real de e-mail**) | Registradas e ativas nesta máquina | **Remover aqui antes de registrar na nova** (seção 2.5), senão os dois notebooks disparam e-mail em duplicidade. |
| 4 | Configuração do Claude Code (MCP, skills, memória, permissões) | `.mcp.json` com **caminhos absolutos** desta máquina | Ajustar caminhos; recriar memória global (seção 3). |
| 5 | Outros 10 projetos menores (ata, conciliador, CNPJ, XML fiscal, portal financeiro etc.) | 3 têm GitHub; os demais só existem localmente | Ver tabela da seção 4 e copiar os que interessam. |
| 6 | Programas necessários | Python 3.14, Node 24, Google Chrome, Git, Claude Code (app desktop) | Instalar na nova máquina (seção 1). |

---

## 1. Pré-requisitos na máquina nova

| Software | Versão nesta máquina | Para quê |
|---|---|---|
| **Claude Code (app desktop, aba Code)** | atual | Tudo. Login com a conta `juliobarcelos08@gmail.com`. |
| **Git** | qualquer recente | clonar/atualizar os repositórios (`git user: barcelosjr`). |
| **Python** | 3.14.3 (dentro do `.venv`) | `iaempresarial` e os projetos Python. **Atenção:** o `python` do PATH no Windows costuma ser o *stub da Microsoft Store* — instale o Python oficial (python.org) e marque "Add to PATH". |
| **Node.js** | v24.11.1 | validação de sintaxe dos painéis HTML antes de publicar (skill `atualizar-paineis`, passo 4). |
| **Google Chrome** | instalado em `C:\Program Files\Google\Chrome\` | impressão dos PDFs da DMF do COAF (`analysis/dmf_html.py` usa Chrome headless com perfil próprio). |
| **Power BI Desktop** | instalado | só para os `.pbix` da pasta `C:\relatorio\POWER BI\DIRETORIA\FINANCEIRO` (não é usado pelo `iaempresarial`). |
| **Acesso ao Power BI Service** | conta corporativa com licença Pro, permissão *Read + Build* nos datasets, tenant com *Execute Queries REST API* ligado | login por `device_code` no primeiro `validar_setup.py`. |

---

## 2. Projeto principal: `iaempresarial` (analista-bi)

**Pasta atual:** `C:\Users\Controladoria\.claude\projects\iaempresarial`
**GitHub:** https://github.com/barcelosjr/iaempresarial (branch `main`; existe também a branch `claude/new-session-220kcq`, que foi a origem do projeto e é o `origin/HEAD`)

### 2.0 O que é

Analista de dados da empresa rodando dentro do Claude Code: consulta os modelos
semânticos do Power BI via API REST (`executeQueries` com DAX, **somente
leitura**) através de um **servidor MCP próprio** (`mcp_server/server.py`),
mais uma camada de relatórios financeiros, painéis HTML publicados como Claude
Artifacts, monitoramento COAF automático e conciliação de caixa.

Histórico de commits (o que foi construído, em ordem):

| Data | Commit | Entrega |
|---|---|---|
| 21/07/2026 | `e0af5e4`, `7bf2e0f`, `adb9069` | Projeto base: auth MSAL, `PowerBIClient`, servidor MCP (`consultar_dax`, `buscar_item`, `esquema_modelo`, `resumo_kpis`, `consultar_duckdb`), DuckDB local, briefing diário, testes com mocks. |
| 21/07/2026 | `1b3812f` | `datasets.yaml` corrigido, MCP registrado (`.mcp.json`), specs (`especificacao-projeto-analista-powerbi.md`, `especificacao-agentes.md`). |
| 22/07/2026 | `9efb598`, `cc9db12` | Relatórios financeiros via MCP (`relatorio_dre`, `relatorio_balanco`, `relatorio_fluxo_caixa`) + `design_system_relatorios.md`. |
| 23–24/07/2026 | `c72abf1`, `f024033`, `4284239` | `relatorio_indicadores` (KPIs), regras do Fluxo de Caixa, `.gitignore` de dados reais. |
| 06/08/2026 | `a67dd3a` | 8 painéis financeiros por marca + consolidado com filtro de Ano (`DADOS_ANO`/`aplicarAno`). |
| 31/08/2026 | `9f7d9fa` | Refresh dos 9 painéis e correção do pipeline (`gerar_dados_*_ano.py` + `_atualizar_dados_ano_*.py`). |
| **ago–set/2026 (NÃO COMMITADO)** | — | **COAF recebimentos em espécie** (job + DMF em PDF + e-mail Zoho + histórico DuckDB + agendamento Windows), **conciliação de caixa** financeiro × contábil, **auditoria diária de caixa**, **planilha financeira tabular** (`gerar_planilha.py`), **DRE da KOBE por revenda** (11 painéis + XML + comparativo), **rateio do grupo**, `design_system/coaf-alerta-30-mil/`, `docs/`, `assets/` (logo e fontes Montserrat), `notify/email_zoho.py`, novos testes. |

### 2.1 PASSO OBRIGATÓRIO — commitar e enviar o que está pendente

Rodar **nesta máquina**, na raiz do projeto:

```bash
git -C "C:/Users/Controladoria/.claude/projects/iaempresarial" status --short
```

```bash
git -C "C:/Users/Controladoria/.claude/projects/iaempresarial" add -A
```

```bash
git -C "C:/Users/Controladoria/.claude/projects/iaempresarial" commit -m "Adiciona COAF, conciliacao de caixa, planilha financeira, DRE Kobe por revenda e rateio do grupo"
```

```bash
git -C "C:/Users/Controladoria/.claude/projects/iaempresarial" push origin main
```

O `.gitignore` já protege `.env`, `*.duckdb`, `reports/`, `logs/`, `*.csv`,
`_scratch/`, `.chrome_perfil_dmf/` e `settings.local.json` — nada sensível
sobe. Confira o `git status` antes do `add -A` mesmo assim.

> `MIGRACAO_NOVO_NOTEBOOK.md` (este arquivo) também entra no commit, para
> que o roteiro chegue junto com o clone.

### 2.2 Arquivos que NÃO estão no git — copiar à mão

Copie para o mesmo caminho relativo dentro do clone novo:

| Arquivo/pasta | Por quê | Alternativa se não copiar |
|---|---|---|
| **`.env`** (15 chaves: `AUTH_MODE`, `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `PBI_WORKSPACE_ID`, `PBI_DATASET_ID`, `PBI_RATE_LIMIT_PER_MIN`, `PBI_MAX_RETRIES`, `PBI_DEFAULT_ROW_LIMIT=1000`, `TOKEN_CACHE_PATH`, `ZOHO_SMTP_HOST/PORT/USER/PASSWORD`, `ZOHO_REMETENTE_NOME`) | credenciais Azure/Power BI e senha de aplicativo do Zoho (e-mail do COAF) | recriar a partir de `.env.example` — precisa dos IDs do Azure e gerar nova senha de app no Zoho. **Nunca commitar.** |
| **`local_data/warehouse.duckdb`** (1,8 MB) | tabelas `coaf_deteccao` e `coaf_deteccao_lancamento` — **histórico permanente e append-only do COAF** (exigência de compliance) + snapshots de saldo + planilhas ingeridas | **Não há alternativa.** Sem ele o job reenvia DMF para todo mundo de novo. |
| `reports/` (32 arquivos: `coaf_especie_AAAA-MM-DD.md`, `coaf_historico.md/.csv`, `auditoria_caixa_*.md`, PDFs de DRE/Balanço da KOBE 03/2026) | saídas geradas para a diretoria/compliance | regeneráveis em parte (`--historico --csv`); os diários antigos não. |
| `logs/coaf_2026-08.log`, `logs/coaf_2026-09.log` | trilha de execução do job (contém nomes de clientes) | histórico apenas. |
| `dictionary/modelo_semantico.md` | dicionário gerado do modelo | regenerar: `.venv/Scripts/python.exe scripts/gerar_dicionario.py` |
| `Dashboard financeiro/_scratch/*.js` | intermediários da atualização de painel | regenerados pela skill `atualizar-paineis`. |
| `.claude/settings.local.json` | permissões locais de PowerShell aprovadas | irrelevante; será recriado conforme você aprova comandos. |
| `.token_cache.json` | cache do login `device_code` | **não existe hoje** (expirou) — o primeiro `validar_setup.py` pede login de novo. |
| `.chrome_perfil_dmf/` | perfil do Chrome para imprimir DMF | recriado sozinho. |
| `docs/MODELO DOC — GRUPO MULT.docx`, `assets/` | modelo de documento e logo/fontes | **estão untracked** — entram no commit da seção 2.1. |

### 2.3 Setup na máquina nova

```bash
git clone https://github.com/barcelosjr/iaempresarial.git "C:/Users/<USUARIO>/.claude/projects/iaempresarial"
```

```bash
cd "C:/Users/<USUARIO>/.claude/projects/iaempresarial" && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt
```

Dependências (`requirements.txt`): `msal`, `requests`, `python-dotenv`,
`pyyaml`, `duckdb`, `pandas`, `openpyxl`, `mcp`, `pytest`, `reportlab`.

Depois de colar o `.env` e o `warehouse.duckdb`:

```bash
.venv/Scripts/python.exe scripts/validar_setup.py
```

(abre o fluxo `device_code`: URL + código, login com a conta corporativa; o
token fica em `.token_cache.json`).

```bash
.venv/Scripts/python.exe scripts/gerar_dicionario.py
```

```bash
.venv/Scripts/python.exe -m pytest -q
```

### 2.4 Registrar o servidor MCP no Claude Code

O arquivo **`.mcp.json` está versionado, mas com caminhos absolutos desta
máquina**:

```json
{
  "mcpServers": {
    "analista-bi": {
      "command": "C:/Users/Controladoria/.claude/projects/iaempresarial/.venv/Scripts/python.exe",
      "args": ["C:/Users/Controladoria/.claude/projects/iaempresarial/mcp_server/server.py"]
    }
  }
}
```

Na máquina nova, troque `Controladoria` pelo usuário Windows novo (ou mantenha
o mesmo nome de usuário e nada muda). Reinicie o Claude Code e aceite o
diálogo de confiança do projeto. Ferramentas que devem aparecer
(`mcp__analista-bi__*`): `consultar_dax`, `buscar_item`, `esquema_modelo`,
`resumo_kpis`, `consultar_duckdb`, `periodos_financeiros`, `relatorio_dre`,
`relatorio_balanco`, `relatorio_fluxo_caixa`, `relatorio_indicadores`,
`relatorio_conciliacao_caixa`, `relatorio_auditoria`, `relatorio_coaf`,
`historico_coaf`.

> O `PBI_DEFAULT_ROW_LIMIT` (1000) é lido uma vez na inicialização do servidor
> MCP — mudanças no `.env` exigem reiniciar o Claude Code.

### 2.5 Tarefas agendadas do Windows (COAF) — cuidado com duplicidade

Hoje existem duas tarefas **ativas** no Agendador desta máquina, rodando
`scripts\coaf_job_notificar.ps1 -Enviar` (**envio real de e-mail**):

| Tarefa | Janela | Frequência |
|---|---|---|
| `COAF-Especie-Semana` | seg–sex 07:00–19:00 | a cada 30 min |
| `COAF-Especie-Sabado` | sábado 07:00–12:00 | a cada 30 min |

Ordem correta na migração:

1. **Nesta máquina, remover** (para não mandar e-mail em dobro):
   ```bash
   powershell -ExecutionPolicy Bypass -File "C:/Users/Controladoria/.claude/projects/iaempresarial/scripts/coaf_agendar.ps1" -Remover
   ```
2. Copiar o `warehouse.duckdb` **depois** da última execução aqui (para levar o
   histórico completo).
3. Na máquina nova, com `.env` + DuckDB no lugar e login feito, registrar
   primeiro em modo revisão e conferir um relatório em `reports/`:
   ```bash
   powershell -ExecutionPolicy Bypass -File scripts/coaf_agendar.ps1
   ```
4. Só então religar o envio:
   ```bash
   powershell -ExecutionPolicy Bypass -File scripts/coaf_agendar.ps1 -Enviar
   ```

As tarefas rodam na sessão do usuário logado (exigência do cache de token do
`device_code`). Quando o refresh token expirar, o job falha no log e basta
rodar `validar_setup.py` de novo.

### 2.6 Artifacts publicados (painéis no claude.ai)

Os painéis vivem em `Dashboard financeiro/build/` e são publicados como
Claude Artifacts. As URLs ficam na skill `.claude/skills/atualizar-paineis/SKILL.md`
(seção 5) — são vinculadas à conta, não à máquina, então continuam valendo:

| Painel | Arquivo | URL |
|---|---|---|
| Consolidado Grupo Mult | `painel_financeiro.html` | https://claude.ai/code/artifact/4f2b423a-c88a-4258-8d3b-b8156abe6bb3 |
| CORRETORA | `painel_financeiro_corretora.html` | https://claude.ai/artifact/HNeYHe2j8pcxG8mjoFjup3 |
| ROYAL ENFIELD | `painel_financeiro_royal.html` | https://claude.ai/code/artifact/374cba84-1a94-4f7e-a755-e89619f38ac1 |
| KOBE | `painel_financeiro_kobe.html` | https://claude.ai/code/artifact/e8d50b8e-ff41-4071-9458-d15434c684ae |
| MIT | `painel_financeiro_mit.html` | https://claude.ai/code/artifact/954236f2-d4f9-4eb3-b979-42a61a92f4fc |
| MEGA STORE | `painel_financeiro_megastore.html` | https://claude.ai/code/artifact/6baaaa69-9304-4c6e-8306-bddc9ad2d1f0 |
| MULT BOATS | `painel_financeiro_multboats.html` | https://claude.ai/code/artifact/7dfc3452-2f5e-40d0-a773-6f7af7044e91 |
| OMODA | `painel_financeiro_omoda.html` | https://claude.ai/code/artifact/b03f2fa6-85a6-4bbc-90ed-e03a1ae0f55d |
| MULT SOLUÇÕES | `painel_financeiro_multsolucoes.html` | https://claude.ai/code/artifact/4aae7a65-5107-4d25-b89f-d95237102b9c |

Os 11 painéis da KOBE por revenda (`kobe_gv/sh/ci/ip/li/vi/vv/mh/bh/ct` +
`kobe_por_revenda`) e as planilhas (`planilha_royal.html`,
`planilha_kobe_por_revenda.html`) **nunca foram publicados** — só existem
como HTML local.

Numa conversa nova em outra máquina, para atualizar um artifact existente
o Claude precisa passar `url:` — sem isso cria um link novo e duplicado.

### 2.7 Mapa do projeto (para orientar o Claude na máquina nova)

```
CLAUDE.md                     memória do projeto (regras: só leitura, skill comandos primeiro)
.claude/skills/comandos/      catálogo oficial de comandos/ferramentas — invocar em toda tarefa
.claude/skills/atualizar-paineis/  checklist de refresh + publicação dos 9 painéis
.mcp.json                     registro do servidor MCP (caminhos absolutos!)
config/                       settings.py, datasets.yaml, coaf.yaml, conciliacao_caixa.yaml, responsaveis_caixa.yaml
auth/azure_auth.py            MSAL (device_code | service_principal)
powerbi/                      client.py, schema.py, dax_lib.py, dax_financeiro.py, dax_kpis.py, dax_coaf.py, dax_conciliacao.py, dax_auditoria.py
mcp_server/server.py          ferramentas MCP
analysis/                     briefing_diario, auditoria_diaria, conciliacao_caixa, coaf_especie, dmf_html, dmf_pdf
notify/email_zoho.py          envio SMTP (COAF)
local_data/                   ingest.py, snapshots.py, coaf_estado.py, warehouse.duckdb (fora do git)
dictionary/                   regras_negocio.md (manual, versionado), modelo_semantico.md (gerado)
Dashboard financeiro/         geradores + templates + build/ (painéis e planilhas HTML)
design_system/coaf-alerta-30-mil/  templates dos e-mails/DMF do COAF
docs/                         modelo .docx do grupo, HTMLs de referência
memory/                       notas de contexto do projeto (5 arquivos, versionados)
scripts/                      validar_setup, gerar_dicionario, coaf_agendar.ps1, coaf_job.bat, coaf_job_notificar.ps1
tests/                        pytest com mocks
estrutura_financeira_completa.md, design_system_relatorios.md, regras_claude_lgpd_powerbi_dax.md, especificacao-*.md
```

Datasets (`config/datasets.yaml`): o padrão vem do `.env`
(`PBI_WORKSPACE_ID`/`PBI_DATASET_ID` = lançamentos contábeis, workspace
DIRETORIA); o apelido `controlador` aponta para o modelo de lançamentos de
caixa (tabela `CAIXAS`), usado pelo COAF e pela conciliação. Os apelidos
`vendas`, `financeiro`, `contabil` ainda têm GUID placeholder.

---

## 3. Configuração do Claude Code nesta máquina

### 3.1 Global (`C:\Users\Controladoria\.claude\`)

| Item | Conteúdo | Migrar? |
|---|---|---|
| `settings.json` | apenas `inputNeededNotifEnabled` e `agentPushNotifEnabled` = true | opcional (2 toggles de notificação). |
| `CLAUDE.md` global | **não existe** | — |
| MCP globais (`~/.claude.json` → `mcpServers`) | **nenhum** — o único MCP é o `.mcp.json` do projeto | — |
| Plugins/skills globais | nenhum instalado além dos padrão da Anthropic | — |
| `plans/` | 3 planos antigos de sessões (`crie-um-planejamento…`, `o-setor-responsavel…`, `preciso-de-um-aplicativo…`) | não precisa. |

### 3.2 Memória automática do Claude (por projeto)

Fica em `C:\Users\Controladoria\.claude\projects\<caminho-codificado>\memory\`.
São notas que o Claude escreveu sobre preferências e contexto. **Vale copiar
a pasta `memory/` de cada projeto** para o mesmo caminho na máquina nova (o
caminho codificado muda se o usuário Windows mudar de nome — ex.
`C--Users-Controladoria--claude-projects-iaempresarial` →
`C--Users-<NOVO>--claude-projects-iaempresarial`).

| Projeto | Memórias |
|---|---|
| `iaempresarial` | `feedback_snapshot_date.md` — sempre gravar `SNAPSHOT` com a data real do refresh do painel. |
| `financialreports` | service principal `portal-site-powerbi` (workspace DIRETORIA, dataset lancamentos_contabeis, Build obrigatório); plano do backend PHP na Hostinger (fases 0/1/2 em produção, 3a validada em dev, deploy pendente); como PHP 8.3/MySQL 8.4 foram instalados sem admin. |
| `ConciliadorContabil` | modelo de dados do conciliador (referencias.xlsx 5 abas + lancamentos.xlsx), hipótese REFCRUZADA em aberto. |
| `HUB SIEG/XML` | contexto do grupo (concessionárias Nissan, Mitsubishi/HPE, Royal Enfield, Comfort; 8 raízes de CNPJ, ~19 filiais); auditoria de notas de entrada a partir dos `NFe_*.xlsx`. |
| `POWER BI/DIRETORIA/FINANCEIRO` | **nunca publicar** nada em nome do usuário (Power BI Service, Artifact); inventário das 127 medidas DAX em `C:\Users\Controladoria\RELATÓRIOS\DIRETORIA\TODAS_AS_MEDIDAS.dax`. |

Além dessas, o `iaempresarial` tem uma pasta `memory/` **dentro do repositório**
(versionada) com 5 notas: estrutura oficial da DRE (7 grupos, não simplificar),
limite de 1000 linhas/truncamento, contexto e arquitetura do painel da
CORRETORA, e o padrão de explicar KPIs para a diretoria em uma frase.

### 3.3 Transcrições das sessões

`~/.claude/projects/C--…/*.jsonl` são os históricos de conversa (o do
`iaempresarial` tem 62 MB, 33 arquivos). Não são necessários para o projeto
funcionar; copie só se quiser reabrir sessões antigas.

---

## 4. Outros projetos feitos com o Claude Code nesta máquina

Todos em `C:\Users\Controladoria\.claude\projects\` salvo indicação.

| Projeto | O que é | Git | Estado / o que copiar |
|---|---|---|---|
| **financialreports** | Portal financeiro `financialreports.com.br`: front React 19 (Vite+Tailwind+Recharts) + backend Node (especificação) + **backend PHP/MySQL na Hostinger** (`portal-backend-php`, `deploy/`). Lê o Power BI via service principal. | https://github.com/barcelosjr/financialreports (24 commits, limpo, último 19/07/2026) | Clonar. Fases 0–2 em produção; **Fase 3a pronta em dev, deploy pendente**; 3b não iniciada (ver `PLANO.md`). Segredos do `.env`/deploy não estão no git. |
| **controller** | "Motor analítico" do grupo de concessionárias: `motor/` em Python, `Fluxo_Caixa_13_Semanas.xlsx`, `painel.html`, manual de implantação, política de caixa `.docx`, skill `pauta-diretoria`. | https://github.com/barcelosjr/controller (1 commit, limpo, 28/07/2026) | Clonar. Usa `py -3.13` + `requisitos.txt` (pandas 2.x fixo). |
| **ConciliadorContabil** | `conciliador.py` — conciliação de lançamentos do ERP (`referencias.xlsx`, `lancamentos.xlsx`, `rateios.docx`). | https://github.com/barcelosjr/ConciliadorContabil (1 commit, 14/07/2026) | **5 alterações não commitadas** (`conciliador.py`, planilhas, `notas_header.txt`) — commitar/push ou copiar a pasta. |
| **ConciliadorParaContabilidade** | Versão mais completa do conciliador em `claude/accounting-reconciler-jj3lax/` (pacote Python com `src/`, `sql/`, `tests/`, `pyproject.toml`, `config/`, `saida/`). 81 MB. | **sem git** | Copiar a pasta inteira. |
| **ata_diretoria** | Gerador de ata de reunião de diretoria (PDF + resumo de e-mail): `app_gui.py` (Tkinter), `gerar_ata.py`, `empresas.json`, executável `dist/GeradorDeAta.exe` (PyInstaller), atas em `reunioes/`. 30 MB. | sem git | Copiar. Reconstruir exe: `python -m PyInstaller --onefile --windowed --name GeradorDeAta app_gui.py`. |
| **verificar_cnpj_fornecedores** | Consulta offline de CNPJ na base aberta da Receita (`consultar.py`, `baixar_base.py`, `layouts.py`); entrada `lista_cnpj.xlsx`, saída em `saida/`. | sem git | Copiar os `.py` + README. A pasta `dados/` (base da Receita, ~7,6 GB) pode ser rebaixada com `baixar_base.py`. |
| **AtualizacaoPlanilhasGrupo** | Modelo analítico de vendas/concessionárias (Oracle → Power Query → Power Pivot): `_docs/` (plano, dicionário, roteiro) e `_lib/` (código M e medidas DAX). Fase 0 concluída; Fase 1 depende de preencher `_docs/02_Mapeamento_Consulta_Atual.md`. | sem git | Copiar (133 KB). |
| **PlanilhasGrupo** | Bases Excel: `vendas/BASE Vendas Grupo Mult.xlsx`, `vendas/Analise Gerencial de Vendas.xlsx`, `pos-venda/BASE Pós-venda Grupo Mult.xlsx`. | sem git | Copiar se ainda usadas. |
| **juntarpdf** | Utilitário Tkinter para juntar PDFs (`juntar_pdf.py`, `pypdf` + `tkinterdnd2`), exe em `dist/`. | sem git | Copiar. |
| **rateioDespesas** | Só `lançamentos.xlsx` — trabalho não avançou. | sem git | Opcional. |
| **AcompanhamentoEmailWhatsapp**, **auditoria_sped** | Só há transcrição de sessão, sem pasta de projeto. | — | Nada a copiar. |

Pastas de trabalho **fora** de `.claude/projects` onde o Claude Code também foi usado:

| Pasta | O que há | Migrar |
|---|---|---|
| `C:\Users\Controladoria\HUB SIEG\XML` | `extrator_xml.py` (NF-e/CT-e/NFS-e → Excel), `verificador_entradas.py`, `Extrator.bat`, XMLs por CNPJ; relatórios em `C:\Users\Controladoria\HUB SIEG\Relatórios`. | Copiar os `.py`/`.bat`; os XMLs vêm do HUB SIEG. |
| `C:\relatorio\POWER BI\DIRETORIA\FINANCEIRO` | `.pbix` (RESULTADO FINANCEIRO, lancamentos_contabeis, lancamentos_financeiros, COBRANÇA DE SEGURADORA), `.rdl`, e `html-content/` (gerador de blocos HTML, medidas DAX, `preview-completo.html`). | Copiar; é o modelo que alimenta o `iaempresarial`. |
| `C:\Users\Controladoria\RELATÓRIOS\DIRETORIA\TODAS_AS_MEDIDAS.dax` | inventário das 127 medidas DAX do modelo financeiro. | **Copiar** — referência obrigatória antes de escrever DAX novo. |
| `C:\FLUXO DE CAIXA\CLAUDE` | vazia. | Nada. |

---

## 5. Checklist final de migração

- [ ] `git add -A && git commit && git push` no `iaempresarial` (seção 2.1)
- [ ] Commitar/push (ou copiar) o `ConciliadorContabil`
- [ ] Copiar `.env` do `iaempresarial` (ou recriar; gerar senha de app Zoho nova)
- [ ] Remover as tarefas COAF aqui (`coaf_agendar.ps1 -Remover`) **antes** de copiar o DuckDB
- [ ] Copiar `local_data/warehouse.duckdb`, `reports/`, `logs/`
- [ ] Copiar as pastas `memory/` de `~/.claude/projects/C--…/` (seção 3.2)
- [ ] Copiar projetos sem git (seção 4) e as 3 pastas externas
- [ ] Máquina nova: instalar Python 3.14, Node 24, Chrome, Git, Claude Code
- [ ] Clonar os 4 repositórios GitHub (`iaempresarial`, `financialreports`, `controller`, `ConciliadorContabil`)
- [ ] `iaempresarial`: venv + `pip install -r requirements.txt`, colar `.env` + DuckDB, ajustar `.mcp.json`, `validar_setup.py` (login), `gerar_dicionario.py`, `pytest -q`
- [ ] Abrir o projeto no Claude Code, aceitar a confiança, conferir que as 14 ferramentas `mcp__analista-bi__*` aparecem
- [ ] Registrar o COAF em modo revisão → conferir → `-Enviar`
- [ ] Testar a skill `atualizar-paineis` num painel só (ex. CORRETORA) e confirmar que o artifact existente foi atualizado (não duplicado)
