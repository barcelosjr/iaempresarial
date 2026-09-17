---
name: feedback-explicacoes-diretoria
description: Como explicar KPIs financeiros pro usuário/diretoria — frase única, linguagem de criança, sem poluir o layout do painel
metadata:
  type: feedback
---

**Quando o usuário pede pra explicar um KPI "para a diretoria" ou "como se fosse pra uma criança", a régua é literal: uma frase curta, sem jargão financeiro, com uma imagem concreta do dia a dia.**

**Why:** pedido explícito duas vezes na mesma sessão (explicação de Capital de Giro, depois de ROE/ROA/Liquidez/Endividamento em lote). A primeira resposta aceita foi "O troco que sobra depois de pagar tudo que você deve agora." — esse é o calibre certo: uma oração, sem "ativo circulante" nem "passivo", uma cena que qualquer leigo visualiza na hora.

**How to apply:**

- Evite termos técnicos mesmo que "corretos" (ex.: não diga "ativo circulante menos passivo circulante" — diga "o que você tem pra pagar menos o que você deve logo").
- Uma frase por KPI. Não vira parágrafo, não empilha "e também", não lista exceções.
- Quando o pedido é pra **incluir a frase no painel** (não só responder no chat), o lugar certo é o espaço de subtítulo que os cards de KPI já têm (`.kpi-sub`) — reaproveite esse espaço em vez de criar elemento novo. Se o card já tinha um texto técnico ali (tipo "EBIT ÷ Despesas Financeiras"), **troque** pelo texto simples em vez de acrescentar os dois — o usuário foi explícito: "pra não ficar os cards poluídos".
- Confirme visualmente (screenshot ou leitura do texto renderizado) que a frase não estourou o card antes de considerar terminado.

Ver [[dashboard-corretora-contexto]] para onde essas frases foram aplicadas (painel da CORRETORA, página de Rentabilidade/Liquidez/Endividamento).
