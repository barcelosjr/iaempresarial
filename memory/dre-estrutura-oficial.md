---
name: dre-estrutura-oficial
description: A DRE deve sempre sair nos 7 grupos e subgrupos oficiais — não simplificar sem pedido
metadata:
  type: feedback
---

**Nunca altere a estrutura da DRE por conta própria.** Ela tem 7 grupos com seus subgrupos, e é assim que o gestor lê. Eu colapsei a DRE por empresa em blocos (só Receita Líquida → Lucro Bruto → EBITDA → ...) e o gestor reclamou: a estrutura tinha sido "alterada sem o meu pedido".

**Why:** o gestor confere o painel contra o relatório contábil interno dele, linha por linha. Uma DRE resumida não é uma versão "mais limpa" — é um relatório diferente, que ele não consegue conciliar.

**How to apply:** a estrutura completa está em `estrutura_financeira_completa.md` (raiz do projeto) e implementada em `powerbi/dax_financeiro.py`. Pontos que já me pegaram:

- Existe **regra de adaptação por ramo** nos grupos 1 e 2: concessionárias mostram as linhas 1–5, 9 e 10 (sem as comissões de corretagem); a **CORRETORA** mostra as linhas 6–10 (sem venda de veículos/peças/oficina) e o custo em **linha única "Custo de Mercado e Serviço"**; o consolidado mostra tudo. É só apresentação — nenhum subtotal muda.
- Linhas subtrativas aparecem com o **sinal invertido** na exibição (custo negativo na base sai positivo no relatório; um estorno sai negativo). Não use `Math.abs`, use a inversão — senão um estorno vira despesa.
- Os blocos 3, 4 e 6 exibem um **subtotal só de apresentação** no cabeçalho da faixa.
- Em 31/07/2026 "Despesas Gerais e Rateio do Grupo" foi **desmembrada** em `Rateio do Grupo` e `Despesas Gerais de Funcionamento`. Por um tempo a conta antiga sobreviveu só na CORRETORA (34→36 contas), mas em 03/08/2026 o gestor reclassificou os lançamentos históricos dela também — confirmado com `GROUPBY`: 0 linhas em toda a base, todas as empresas. A conta saiu de vez da estrutura (34→35 contas: 12 despesas em vez de 11, sem a linha antiga).
- **Quando o gestor disser que "retirou" uma conta, confira na base antes de removê-la.** Confirme com um `GROUPBY` da coluna `DRE` por período/empresa se ainda há lançamentos — o que ele mudou pode valer só para parte das empresas.
- **Conta nova no modelo que ninguém mapeou some em silêncio.** Foi o que aconteceu aqui: o gerador do painel ignorava contas fora do mapa, e R$ 6,28 milhões de despesas Jan–Jul/2026 ficaram de fora — EBITDA e Lucro Líquido saíram inflados, e a conferência contra `relatorio_dre` passou porque os **dois lados** usavam a mesma estrutura desatualizada. Hoje `Dashboard financeiro/atualizar_dados.py` aborta com `_conferir_cobertura` se aparecer conta sem chave.

Ver também [[limite-linhas-e-truncamento]] — o detalhe conta a conta por empresa são 197 linhas numa consulta só.
