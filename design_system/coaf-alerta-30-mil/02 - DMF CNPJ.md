# 2. DMF — Declarante Pessoa Jurídica (CNPJ)

Arquivo: `DMF CNPJ.dc.html`
Base de estilo: `00 - BASE (comum aos 3).md` (obrigatória)
Subtítulo do cabeçalho: `Declaração de Movimentação Financeira (DMF) — {{MARCA}}`

Usar esta variante quando o declarante for pessoa jurídica. As linhas
(Profissão), (Servidor público) e (Politicamente exposto) **não existem**
neste template — a numeração é **sequencial, sem lacunas**: 1, 2, 3, 4, 5, 6
(decisão do gestor, 21/08/2026 — a versão anterior pulava de 2 para 6 para
preservar os números 3/4/5 da variante CPF; o gestor preferiu renumerar em
vez de deixar lacuna).

## Estrutura (ordem fixa)

1. H1 `Declaração de Movimentação Financeira`
2. Linha de apoio (texto fixo sobre a obrigatoriedade acima de R$ 30.000,00)
3. Caixa de metadados (Empresa · Revenda · Caixa(s) · Responsável pelo caixa · Período apurado · Recebimentos)
4. Seção `Identificação do declarante` — campos 1 e 2
5. Seção `Valor declarado` — campo 3
6. Seção `Demonstrativo dos recebimentos em espécie — últimos 6 meses` (tabela)
7. Seção `Natureza da operação e assinatura` — campos 4, 5, 6
8. Bloco de assinatura

## Campos variáveis

### Caixa de metadados
| Rótulo (fixo) | Token | Formato |
|---|---|---|
| Empresa | `{{COD_EMPRESA}} - {{RAZAO_EMPRESA}}` | `6 - MULTI COMERCIO DE VEICULOS LTDA` |
| Revenda | `{{REVENDA}}` | maiúsculas |
| Caixa(s) | `{{CAIXAS}}` | números separados por vírgula |
| Responsável pelo caixa | `{{RESPONSAVEL_CAIXA}}` | nome próprio |
| Período apurado | `{{PERIODO}}` | `dd/mm/aaaa a dd/mm/aaaa` |
| Recebimentos | `{{QTD_RECEBIMENTOS}}` | inteiro |

### Identificação do declarante
| Nº | Rótulo (fixo) | Token | Formato |
|---|---|---|---|
| 1 | Razão social | `{{RAZAO_SOCIAL}}` | maiúsculas, peso 600 |
| 2 | CNPJ | `{{CNPJ}}` | `##.###.###/####-##`, peso 600 |

### Valor declarado
| Nº | Rótulo (fixo) | Token | Formato |
|---|---|---|---|
| 3 | Valor recebido em espécie | `{{VALOR_TOTAL}}` | `R$ #.###,##`, 19px/600 |

`{{VALOR_TOTAL}}` = total da tabela do demonstrativo. Os dois valores
nunca podem divergir.

### Tabela — Demonstrativo (6 colunas)
Data · Revenda / caixa · Origem · Lançamento · Situação · Valor (R$).

| Token | Formato |
|---|---|
| `{{DATA}}` | `dd/mm/aaaa` (`white-space: nowrap`) |
| `{{REVENDA}} / {{CAIXA}}` | maiúsculas |
| `{{ORIGEM}}` | `### - DESCRIÇÃO` |
| `{{LANÇAMENTO}}` | número |
| `{{SITUACAO}}` | minúsculas |
| `{{VALOR}}` | `#.###,##`, à direita |

Linha de total: rótulo `Total` com `colspan="5"`. Ordenar por data
crescente. Apenas recebimentos dos últimos 6 meses.

### Natureza da operação e assinatura
| Nº | Rótulo (fixo) | Conteúdo |
|---|---|---|
| 4 | Natureza compra | caixas fixas `( ) ESTOQUE  ( ) VENDA DIRETA` — nunca pré-marcar |
| 5 | Modelo do bem | traço pontilhado para preenchimento manual |
| 6 | Data | `____ / ____ / ________` fixo |

Bloco de assinatura: linha + legenda `ASSINATURA`, igual ao template CPF.
**Sem nome impresso** — nunca acrescentar `{{RESPONSAVEL_CAIXA}}` ou
qualquer outro nome abaixo da legenda.

## Checagem antes de entregar

- Numeração visível: 1, 2, 3, 4, 5, 6 — sequencial, sem lacunas.
- `{{VALOR_TOTAL}}` = total da tabela.
- `{{QTD_RECEBIMENTOS}}` = número de linhas da tabela.
- Total ≥ R$ 30.000,00 (abaixo disso o documento não é exigido).
- Documento em 1 página A4.
