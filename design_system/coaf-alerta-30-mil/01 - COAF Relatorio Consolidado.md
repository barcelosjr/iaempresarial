# 1. COAF — Relatório Consolidado

Arquivo: `COAF - Relatorio Consolidado.dc.html`
Base de estilo: `00 - BASE (comum aos 3).md` (obrigatória)
Subtítulo do cabeçalho (fixo): `Relatório consolidado COAF — uso interno de compliance`

Documento de uma página, uso interno do setor de compliance. Registra o
acumulado de recebimentos em espécie do cliente no grupo e identifica o
lançamento que gerou a obrigação de declarar.

## Estrutura (ordem fixa)

1. H1 `Relatório consolidado — recebimentos em espécie`
2. Linha de identificação: Cliente · Período
3. Seção `Acumulado por empresa do grupo` (tabela)
4. Seção `Lançamento que disparou a obrigação de declarar` (bloco de metadados)
5. Seção `Todos os recebimentos do período — grupo consolidado` (tabela)
6. Nota de encerramento

Nenhuma seção pode ser adicionada, removida ou reordenada.

## Campos variáveis

### Identificação
| Token | Fonte | Formato |
|---|---|---|
| `{{CLIENTE}}` | razão social/nome do cliente | maiúsculas |
| `{{PERIODO}}` | período apurado | `dd/mm/aaaa a dd/mm/aaaa` |
| `{{DATA_GERACAO}}` (rodapé) | data/hora de geração | `dd/mm/aaaa` |

### Tabela — Acumulado por empresa do grupo
Colunas fixas: Empresa / marca · Recebimentos · Valor (R$) · % do total.
Uma linha por empresa/marca com recebimentos no período, depois a linha
`Total do grupo` (`colspan` do rótulo = 1, valores somados).

| Token | Formato |
|---|---|
| `{{EMPRESA_MARCA}}` | maiúsculas, peso 600 |
| `{{QTD_RECEBIMENTOS}}` | inteiro |
| `{{VALOR_EMPRESA}}` | `#.###,##` |
| `{{PCT_TOTAL}}` | `##,#%` |

Regra: soma das linhas = `Total do grupo`; soma dos percentuais = `100,0%`.

### Bloco — Lançamento que disparou a obrigação de declarar
Grid 2 colunas, 6 pares mini-label/valor, nesta ordem:

| Rótulo (fixo) | Token | Formato |
|---|---|---|
| Revenda / caixa | `{{REVENDA}} / caixa {{CAIXA}}` | maiúsculas + número |
| Data do lançamento | `{{DATA_GATILHO}}` | `dd/mm/aaaa` |
| Usuário do sistema | `{{USUARIO_SISTEMA}}` | nome completo, maiúsculas |
| Origem | `{{ORIGEM}}` | `### - DESCRIÇÃO` |
| Lançamento | `{{NUM_LANCAMENTO}}` | número do título |
| Valor do lançamento | `{{VALOR_GATILHO}}` | `R$ #.###,##` |
| Acumulado no período | `{{ACUMULADO}}` | `R$ #.###,##` |

O lançamento a usar aqui é sempre aquele que **levou o acumulado do
cliente a atingir o limiar** — não o maior valor nem o mais recente.

### Tabela — Todos os recebimentos do período
Colunas fixas, nesta ordem (7): Data · Revenda / caixa · Origem ·
Lançamento · Usuário · Situação · Valor (R$).

| Token | Formato |
|---|---|
| `{{DATA}}` | `dd/mm/aaaa` |
| `{{REVENDA}} / {{CAIXA}}` | maiúsculas |
| `{{ORIGEM}}` | `### - DESCRIÇÃO` |
| `{{NUM_LANCAMENTO}}` | número |
| `{{USUARIO}}` | primeiro nome, maiúsculas (ex.: `TAMIRIS`) |
| `{{SITUACAO}}` | minúsculas (`já declarado`) |
| `{{VALOR}}` | `#.###,##`, alinhado à direita |

Linha de total: rótulo `Total` com `colspan="6"` + valor em 12.5px/600.
Ao acrescentar ou remover linhas, manter `colspan="6"`.

Todas as células desta tabela usam `white-space: nowrap` e fonte 9.5px
(`th` 8px). Sem quebra de linha em nenhuma célula.

Ordenação: por data crescente.

### Nota de encerramento
Texto fixo, 9.5px, `#5a5a5a`, largura 100%:
`Os valores são apurados a partir dos lançamentos de caixa e conferem com os registros do período.`

## Checagem antes de entregar

- Total da tabela detalhada = Total do grupo = soma das linhas.
- Quantidade de linhas detalhadas = soma da coluna Recebimentos.
- `{{ACUMULADO}}` ≥ limiar de declaração (R$ 30.000,00).
- Documento continua em 1 página A4.
- Nenhuma célula com quebra de linha.
