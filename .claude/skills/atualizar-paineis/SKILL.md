---
name: atualizar-paineis
description: Checklist executável para "atualizar os dados do(s) painel(éis) financeiro(s)" (Corretora, Royal, Kobe, MIT, Mega Store, Mult Boats, Omoda, Mult Soluções, Consolidado — e, se pedido, Kobe por revenda). Use SEMPRE que o usuário pedir para atualizar/atualiza/refresh os dados de um painel/dashboard financeiro — siga os passos abaixo na ordem, sem parar pra decidir o processo de novo a cada vez.
---

# Atualizar dados dos painéis financeiros

Checklist fixo — execute na ordem, sem pular etapas de validação. Não é um
guia de referência para "pensar a partir dele": rode os comandos como estão.

## 0. Escopo do pedido

- "Atualize os dados dos painéis" (genérico, plural) = os **9 painéis
  principais** da tabela da seção 5. **Não inclui** Kobe por revenda —
  só entra se o usuário pedir explicitamente (ver seção 6).
- "Atualize o painel da CORRETORA" (uma marca só) = só aquele arquivo +
  publicação, pule os outros.
- Se não estiver claro quais painéis, pergunte antes de rodar tudo.

## 1. Checar o período disponível

Rode a ferramenta MCP `periodos_financeiros` primeiro. Confirme o mês mais
recente (ex.: `08/2026` → `mes-final=8`). **Não assuma** que é o mesmo mês da
última vez — a base pode ter avançado.

## 2. Cada painel de marca única

Empresas e arquivos:

| Empresa (`--empresa`) | Arquivo (`--html`) |
|---|---|
| `CORRETORA` | `painel_financeiro_corretora.html` |
| `ROYAL` | `painel_financeiro_royal.html` |
| `KOBE` | `painel_financeiro_kobe.html` |
| `MIT` | `painel_financeiro_mit.html` |
| `MEGA STORE` | `painel_financeiro_megastore.html` |
| `MULT BOATS` | `painel_financeiro_multboats.html` |
| `OMODA` | `painel_financeiro_omoda.html` |
| `MULT SOLUÇÕES` | `painel_financeiro_multsolucoes.html` |

Para cada uma, com `<N>` = mes-final do passo 1:

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa "<EMPRESA>" --ano 2026 --mes-final <N> > "Dashboard financeiro/_scratch/ano_2026.js"
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa "<EMPRESA>" --ano 2025 --mes-final 12 > "Dashboard financeiro/_scratch/ano_2025.js"
.venv/Scripts/python.exe "Dashboard financeiro/_atualizar_dados_ano_empresa.py" --html <ARQUIVO> --mes-final-2026 <N>
```

O terceiro comando **já reescreve `var SNAPSHOT` sozinho** com a data real de
hoje — nunca defina SNAPSHOT manualmente numa chamada separada, e nunca
reaproveite uma data usada num turno anterior da conversa.

`Dashboard financeiro/_scratch/` é uma pasta fixa do projeto (git-ignorada) —
não use a scratchpad temporária da sessão para esses dois arquivos, porque ela
não existe mais na sessão seguinte e quebra o comando acima.

## 3. Painel consolidado (Grupo Mult)

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "Dashboard financeiro/gerar_dados_consolidado_ano.py" --ano 2026 --mes-final <N> > "Dashboard financeiro/_scratch/consol_2026.js"
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "Dashboard financeiro/gerar_dados_consolidado_ano.py" --ano 2025 --mes-final 12 > "Dashboard financeiro/_scratch/consol_2025.js"
.venv/Scripts/python.exe "Dashboard financeiro/_atualizar_dados_ano_consolidado.py" --mes-final-2026 <N>
```

Mesma coisa: SNAPSHOT é atualizado sozinho.

`PYTHONIOENCODING=utf-8` é **obrigatório** nos dois `gerar_dados_*_ano.py`
acima (empresa e consolidado) — sem ele, o `MULT SOLUÇÕES` (cedilha/til)
quebra a codificação do arquivo `.js` gerado e o injetor falha com
`UnicodeDecodeError` ao ler de volta. Isso já aconteceu.

**Não use `Dashboard financeiro/atualizar_dados.py`** — é um script antigo, de
antes da arquitetura `DADOS_ANO`/seletor de Ano, e não é compatível com o
painel atual. Fica só como histórico.

## 4. Validar antes de publicar — sempre, sem exceção

Para cada arquivo tocado:

```bash
node -e "
const fs = require('fs');
const html = fs.readFileSync('Dashboard financeiro/build/<ARQUIVO>', 'utf8');
const m = html.match(/<script>([\s\S]*)<\/script>/);
new Function(m[1]);
console.log('OK');
"
```

Se der erro de sintaxe, **pare e corrija** — nunca publique um painel que não
passou nesse check.

## 5. Publicar (ferramenta Artifact)

Sempre com `url:` apontando pro artifact já existente (nunca publique sem
`url` — cria um artifact novo e duplicado). URLs conhecidas:

| Painel | Arquivo | URL do artifact |
|---|---|---|
| Consolidado — Grupo Mult | `painel_financeiro.html` | https://claude.ai/code/artifact/4f2b423a-c88a-4258-8d3b-b8156abe6bb3 |
| CORRETORA | `painel_financeiro_corretora.html` | https://claude.ai/artifact/HNeYHe2j8pcxG8mjoFjup3 (era `.../code/artifact/8497f8e3-...` — a ferramenta passou a devolver esse formato curto pro mesmo artifact) |
| ROYAL ENFIELD | `painel_financeiro_royal.html` | https://claude.ai/code/artifact/374cba84-1a94-4f7e-a755-e89619f38ac1 |
| KOBE | `painel_financeiro_kobe.html` | https://claude.ai/code/artifact/e8d50b8e-ff41-4071-9458-d15434c684ae |
| MIT | `painel_financeiro_mit.html` | https://claude.ai/code/artifact/954236f2-d4f9-4eb3-b979-42a61a92f4fc |
| MEGA STORE | `painel_financeiro_megastore.html` | https://claude.ai/code/artifact/6baaaa69-9304-4c6e-8306-bddc9ad2d1f0 |
| MULT BOATS | `painel_financeiro_multboats.html` | https://claude.ai/code/artifact/7dfc3452-2f5e-40d0-a773-6f7af7044e91 |
| OMODA | `painel_financeiro_omoda.html` | https://claude.ai/code/artifact/b03f2fa6-85a6-4bbc-90ed-e03a1ae0f55d |
| MULT SOLUÇÕES | `painel_financeiro_multsolucoes.html` | https://claude.ai/code/artifact/4aae7a65-5107-4d25-b89f-d95237102b9c |

Se a ferramenta reclamar "hasn't viewed the latest version": tente publicar
de novo primeiro (o aviso costuma ser só o rastreio interno da sessão atual).
Se persistir, confirme com `WebFetch` na URL que a versão publicada tem
SNAPSHOT antigo antes de usar `force:true` — nunca sobrescreva sem checar.

**Se o usuário disser que o link não é o que ele está vendo / está errado**:
pergunte o URL real que ele está usando e **atualize a tabela acima** — já
aconteceu com a Corretora (link antigo `ac0b0833-...` ficou obsoleto, o
correto passou a ser `8497f8e3-...`). Trate a tabela como fonte da verdade
só até o usuário corrigir.

## 6. Kobe por revenda — só se pedido explicitamente

11 arquivos (`kobe_gv/sh/ci/ip/li/vi/vv/mh/bh/ct` + `kobe_por_revenda`),
gerados por:

```bash
.venv/Scripts/python.exe "Dashboard financeiro/gerar_dre_revendas_kobe.py"
.venv/Scripts/python.exe "Dashboard financeiro/gerar_painel_kobe_por_revenda.py"
```

(Ambos já buscam Jan–Ago/2026 por padrão; ajuste o default `mes_final` dentro
de `gerar_dre_revendas_kobe.py`/`gerar_painel_kobe_por_revenda.py` se o mês
mudar.) Esses 11 nunca foram publicados como artifact — **não publique sem
perguntar antes**, mesmo dentro de um pedido de "atualizar tudo".

## 7. Resposta final

Liste só os links atualizados com o período e a data (SNAPSHOT) que ficou —
não narre os comandos rodados.
