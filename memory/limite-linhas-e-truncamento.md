---
name: limite-linhas-e-truncamento
description: Limite de linhas do Power BI é 1000; se uma consulta truncar, avisar antes de atualizar valores
metadata:
  type: feedback
---

O `PBI_DEFAULT_ROW_LIMIT` no `.env` foi elevado de 20 para **1000** (29/07/2026), a pedido do gestor, para que as consultas tragam a informação completa em vez de fatiada.

**Se uma consulta retornar "TRUNCADO" (mais de 1000 linhas), pare e avise o gestor ANTES de atualizar qualquer valor em relatório ou painel.**

**Why:** com o limite de 20, eu vinha quebrando consultas em vários pedaços e corria o risco de montar números a partir de dados parciais sem perceber. O gestor quer decidir o que fazer (agregar mais no servidor, filtrar período, subir o limite) em vez de receber valores construídos sobre um retorno cortado.

**How to apply:** o corte acontece em `mcp_server/server.py` (`df.head(limite)`) — a consulta roda inteira no servidor do Power BI e só a exibição é truncada, então o rodapé "(de N, TRUNCADO)" é o sinal de alerta. Mudanças no `.env` só valem após reiniciar o Claude Code (o valor é lido uma vez na inicialização do servidor MCP). Ver também [[dre-estrutura-oficial]].
