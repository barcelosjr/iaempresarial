# Design System — Documentos de Compliance Grupo Mult

Base comum aos 3 templates. O agente deve seguir este arquivo + o arquivo
específico do documento que está gerando.

Templates:

| # | Arquivo | Uso |
|---|---|---|
| 1 | `COAF - Relatorio Consolidado.dc.html` | Relatório interno de compliance (consolidado do grupo) |
| 2 | `DMF CNPJ.dc.html` | DMF quando o declarante é pessoa jurídica |
| 3 | `DMF CPF.dc.html` | DMF quando o declarante é pessoa física |

## Regra número 1

O agente **só substitui os valores variáveis** listados no arquivo do
documento. Nunca altera:

- estrutura HTML (ordem de seções, grid, tabelas, colspan);
- estilos inline (cores, tamanhos, bordas, espaçamentos);
- rótulos fixos, numeração de campos (1 a 9), textos de observação;
- cabeçalho, rodapé, logotipo, `doc-page` e seus atributos.

Se um dado não existir, deixar o campo com traço de preenchimento
(`______`) ou vazio — nunca inventar valor, nunca remover a linha
(exceção documentada no template DMF CNPJ: linhas 3, 4 e 5 não existem).

## Página

```
<doc-page size="a4" margin="0.6in">
```

A4 retrato, margem 0.6in, cabeçalho e rodapé em `slot` (repetem em toda
página impressa). Nunca escrever `@page`, `break-*` ou fundo no body.

## Tipografia

- Família única: `Montserrat, Helvetica, sans-serif` (Google Fonts, pesos 400/500/600/700).
- Números, datas, valores, CNPJ/CPF, títulos de lançamento: mesma família + `font-variant-numeric: tabular-nums`.

| Papel | Tamanho | Peso | Cor |
|---|---|---|---|
| H1 do documento | 20px / line-height 1.15 / letter-spacing -0.01em | 700 | `#1a1a1a` |
| Linha de apoio sob o H1 | 10px | 400 | `#666666` |
| Título de seção (H2) | 10px, uppercase, letter-spacing 0.16em, `border-bottom: 1px solid #c0000a`, `padding-bottom: 4px` | 700 | `#c0000a` |
| Rótulo de campo (mini-label) | 8.5px, uppercase, letter-spacing 0.12em | 600 | `#767676` |
| Rótulo de linha numerada | 9.5px, uppercase, letter-spacing 0.1em, `min-width: 120px` | 600 | `#666666` |
| Valor de campo | 11.5px | 600 | `#1a1a1a` |
| Corpo / texto base | 11.5px, line-height 1.5 | 400 | `#1a1a1a` |
| Cabeçalho de tabela (th) | 8.5px, uppercase, letter-spacing 0.1em | 700 | `#4a4a4a` |
| Célula de tabela (td) | 10.5px | 400/500 | `#1a1a1a` |
| Nota de pé de seção | 9.5px | 400 | `#5a5a5a` |
| Rodapé | 9.5px | 500 | `#c0000a` (site) e `#767676` (metadados) |

## Cores

| Token | Hex | Uso |
|---|---|---|
| Vermelho da marca | `#c0000a` | régua do cabeçalho, títulos de seção, filete de total, rodapé |
| Vermelho hover/link ativo | `#8d0008` | `a:hover` |
| Vermelho de fundo (destaque) | `#fbf1f1` | fundo do bloco "Valor declarado" |
| Texto principal | `#1a1a1a` | corpo |
| Texto secundário | `#666666` / `#767676` | rótulos, situação |
| Texto de nota | `#5a5a5a` | notas de pé |
| Cinza do cabeçalho impresso | `#434343` | subtítulo do cabeçalho |
| Fundo de bloco | `#fafafa` | caixa de metadados |
| Fundo de cabeçalho de tabela | `#f4f4f4` | `thead tr` |
| Bordas | `#d9d9d9` (bloco), `#e8e8e8` (linhas de campo), `#ebebeb` (linhas de tabela), `#c8c8c8` (base do thead), `#e2e2e2` (nota) | |
| Traço de preenchimento | `1px dotted #b3b3b3` | campos manuscritos |

Nenhuma outra cor é permitida.

## Cabeçalho (idêntico nos 3, muda só o subtítulo)

```html
<div slot="header" style="font-family:Montserrat,Helvetica,sans-serif">
  <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:20px;padding-bottom:10px">
    <img src="./assets/grupo-mult.png" alt="Grupo Mult" style="height:36px;width:auto;display:block">
    <div style="text-align:right;font-size:11px;color:#434343;letter-spacing:0.01em;max-width:62%">{{SUBTITULO_DOCUMENTO}}</div>
  </div>
  <div style="height:2px;background:#c0000a"></div>
</div>
```

Logotipo: sempre `./assets/grupo-mult.png`, altura 36px, à esquerda. Nunca
redesenhar, recolorir ou substituir.

## Rodapé (idêntico nos 3)

```html
<div slot="footer" style="font-family:Montserrat,Helvetica,sans-serif;border-top:1px solid #d9d9d9;padding-top:6px;display:flex;justify-content:space-between;gap:16px;font-size:9.5px;color:#c0000a;font-weight:500;letter-spacing:0.02em">
  <div>www.multigrupo.com.br</div>
  <div style="color:#767676">Gerado em {{DATA_GERACAO}} · uso interno · Página 1</div>
</div>
```

## Componentes

**Caixa de metadados** — grid 2 colunas, `border: 1px solid #d9d9d9`,
`background: #fafafa`, célula `padding: 8px 10px`, mini-label + valor.

**Linha numerada de formulário** — grid `22px 1fr`; coluna 1 = número do
campo (10px, `#767676`); coluna 2 = rótulo (`min-width: 120px`) + valor ou
traço pontilhado; cada linha com `border-bottom: 1px solid #e8e8e8`.

**Bloco de valor declarado** — flex justificado, `border: 1.5px solid #c0000a`,
`background: #fbf1f1`, `padding: 12px 14px`; valor à direita em 19px/600.

**Tabela** — `width:100%; border-collapse:collapse`, `thead` sempre presente
(repete na impressão), `th` alinhado à esquerda (valor à direita), `td`
`padding: 7px 8px`, `border-bottom: 1px solid #ebebeb`. Linha de total:
rótulo com `colspan`, filete `1.5px solid #c0000a`, valor em 12.5px/600.

**Bloco de assinatura** — centralizado, largura 64%, linha
`border-bottom: 1px solid #434343` com 34px de altura, legenda ASSINATURA
em 9px uppercase.

## Formatação de dados (obrigatória)

| Tipo | Formato | Exemplo |
|---|---|---|
| Data | `dd/mm/aaaa` | `21/05/2026` |
| Período | `dd/mm/aaaa a dd/mm/aaaa` | `16/02/2026 a 21/08/2026` |
| Valor em tabela | `#.###,##` sem símbolo | `42.989,00` |
| Valor em destaque | `R$ #.###,##` | `R$ 42.989,00` |
| Percentual | `##,#%` | `100,0%` |
| CNPJ | `##.###.###/####-##` | `14.488.355/0001-86` |
| CPF | `###.###.###-##` | `123.456.789-00` |
| Razão social / cliente / usuário | maiúsculas, como no sistema | `J.P GUEDES FERREIRA` |
| Situação | minúsculas | `já declarado` |
| Campo sem dado | `______` | |

## Impressão

Sem `position: fixed/sticky` no conteúdo, sem unidades de viewport,
`thead` em todas as tabelas longas, nada de quebra manual de página.
Célula de tabela no consolidado usa `white-space: nowrap` — se um valor
novo estourar a largura, reduzir a fonte da tabela em 0.5px, nunca
permitir quebra de linha.
