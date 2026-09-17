# 3. DMF — Declarante Pessoa Física (CPF)

Arquivo: `DMF CPF.dc.html`
Base de estilo: `00 - BASE (comum aos 3).md` (obrigatória)
Subtítulo do cabeçalho: `Declaração de Movimentação Financeira (DMF) — {{MARCA}}`

Usar esta variante quando o declarante for pessoa física. Diferença em
relação ao template CNPJ: campo 2 é CPF e as linhas 3, 4 e 5 existem e
devem ser preenchidas pelo declarante.

## Estrutura (ordem fixa)

1. H1 `Declaração de Movimentação Financeira`
2. Linha de apoio (texto fixo sobre a obrigatoriedade acima de R$ 30.000,00)
3. Caixa de metadados (Empresa · Revenda · Caixa(s) · Responsável pelo caixa · Período apurado · Recebimentos)
4. Seção `Identificação do declarante` — campos 1 a 5
5. Seção `Valor declarado` — campo 6
6. Seção `Demonstrativo dos recebimentos em espécie — últimos 6 meses` (tabela)
7. Seção `Natureza da operação e assinatura` — campos 7, 8, 9
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
| Nº | Rótulo (fixo) | Token / conteúdo | Formato |
|---|---|---|---|
| 1 | Razão social | `{{NOME_DECLARANTE}}` | maiúsculas, peso 600 |
| 2 | CPF | `{{CPF}}` | `###.###.###-##`, peso 600 |
| 3 | Profissão | traço pontilhado | preenchimento manual |
| 4 | Servidor público | `( ) SIM ( ) NÃO ( ) FEDERAL ( ) ESTADUAL ( ) MUNICIPAL` | fixo, nunca pré-marcar |
| 5 | Politicamente exposto | `( ) SIM ( ) NÃO` | fixo, nunca pré-marcar |

Campos 3, 4 e 5 são sempre preenchidos à mão pelo declarante — o agente
não escreve valores neles.

### Valor declarado
| Nº | Rótulo (fixo) | Token | Formato |
|---|---|---|---|
| 6 | Valor total recebido em espécie | `{{VALOR_TOTAL}}` | `R$ #.###,##`, 19px/600 |

`{{VALOR_TOTAL}}` = total da tabela do demonstrativo.

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
| 7 | Natureza compra | `( ) ESTOQUE  ( ) VENDA DIRETA` — nunca pré-marcar |
| 8 | Modelo do bem | traço pontilhado |
| 9 | Data | `____ / ____ / ________` fixo |

Bloco de assinatura: linha + legenda `ASSINATURA`.

## Checagem antes de entregar

- Numeração visível: 1 a 9, completa.
- Campo 2 rotulado `CPF` e no formato de CPF (11 dígitos).
- Campos 3, 4 e 5 em branco / sem marcação.
- `{{VALOR_TOTAL}}` = total da tabela; `{{QTD_RECEBIMENTOS}}` = nº de linhas.
- Documento em 1 página A4.
