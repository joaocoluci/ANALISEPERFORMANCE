# analise-performance

Recebe o pacote de coleta de logs do Sankhya (`server.log_AAAAMMDDHHMMSS.zip`) e, quando
vier junto, o pacote do Monitor de Consultas (`Monitoramento*.zip`), mede o que os pacotes
permitem medir e entrega o documento **Análise de Performance** em DOCX, no padrão
DSTECH v.3 — com as consultas ofensivas pontuadas, as consultas com erro e os pontos de
atenção em seção própria.

Não estima horas e não escreve escopo. Aprovadas as ações, o orçamento é da
`sankhya-estimativa-planejador` + `orcamento-horas-docx`.

## Uso

```bash
# 1. coletar (2,5 GB levam ~5 min; nada é extraído em disco)
python "$HOME/.claude/skills/analise-performance/scripts/coletar_metricas.py" \
  --pacote "server.log_20260901233905.zip" --saida ./analise
# o pacote do Monitor de Consultas na mesma pasta e encontrado pelo conteudo;
# --monitor <caminho> aponta outro, --sem-monitor ignora

# 2. ler ./analise/resumo.md, interpretar, redigir, humanizar, montar o JSON

# 3. gerar
export NODE_PATH="$(npm root -g)"
node "$HOME/.claude/skills/analise-performance/scripts/gerar-diagnostico-docx.js" \
  --content ./analise/dados.json --output "./Analise de Performance - Cliente.docx"

# 4. validar
export PYTHONUTF8=1
python "$HOME/.claude/skills/docx/scripts/office/validate.py" "./Analise de Performance - Cliente.docx"
```

`--rapido` limita a 200 MB por arquivo de log. Serve para inspeção prévia; o resultado é
parcial e o documento precisa dizer isso.

## O que o coletor lê

| Fonte | Responde |
|---|---|
| comentário do zip | ambiente, JVM, argumentos, heap no instante da coleta |
| `server.log`, `stdout` | erros, exceções, códigos ORA, sinais, distribuição por hora |
| `dml_stats` | tempo por objeto de banco, contra os limiares oficiais |
| `conn-stats` | série de conexões a cada 5 minutos |
| `threads.dump` | estado das threads no instante da coleta |
| `.ald` | telas, usuários e serviços mais usados |
| `mge-ds.xml`, `version.properties`, `parametros.properties` | pool, versões, parâmetros |
| `sas-server` | módulos licenciados |
| `Monitor_Consulta.log` + `Monitor_Processos.log` | consulta ofensiva pontuada, consulta com erro, ponto de atenção e quem chamou |

Saída: `evidencias.json` (números completos, insumo interno), `resumo.md` (digest) e
`series.json` (séries densas, só para os gráficos). O `coletar_monitor.py` roda sozinho e
escreve `monitor.json` + `monitor.md` quando só o pacote do monitor chegou.

Do Monitor de Consultas, **valor de parâmetro nunca é guardado** — só a quantidade. É dado
de negócio do cliente.

## Regra central

Achado precisa de **número, fonte e janela de tempo**. Faltando qualquer um, vira
verificação recomendada — com o script ou comando que a confirmaria.

## Base documental

Destilada de material oficial da Sankhya: *Checklist de problemas de performance — Service
Desk*, guia de argumentos do WildFly, guia de boas práticas de JOBs, questionário de
lentidão e os scripts SQL de diagnóstico (Oracle e SQL Server).

## Nota

Não guardar dado real de cliente aqui. `examples/` é genérico.
