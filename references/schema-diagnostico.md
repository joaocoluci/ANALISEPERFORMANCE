# Schema do JSON do documento

Entrada de `scripts/gerar-diagnostico-docx.js`. O documento é dirigido por dados: o JSON
descreve seções e blocos, o gerador aplica o layout DSTECH v.4. Não editar o gerador para
acomodar um documento específico.

Modelo completo em `examples/diagnostico-exemplo.json`.

## Raiz

```json
{
  "titulo": "Análise de Performance",
  "subtitulo": "Nome do Cliente — ambiente de produção",
  "cabecalho": { "area": "...", "elaborador": "...", "aprovador": "...", "versao": "1.0" },
  "identificacao": [["Cliente", "..."], ["Período analisado", "..."]],
  "secoes": [ … ]
}
```

| Campo | Obrigatório | Observação |
|---|---|---|
| `titulo` | não | default `Análise de Performance` |
| `subtitulo` | sim na prática | recebe o filete verde; identifica cliente e ambiente |
| `cabecalho` | não | tabela do cabeçalho das páginas 2+. Descreve o **documento** |
| `identificacao` | sim | tabela de duas colunas no corpo. Descreve a **análise** |
| `secoes` | sim | na ordem em que aparecem |

`cabecalho.versao` é a versão do documento e aparece na capa. **Versão e publicação do
cabeçalho não vêm do JSON** — são do layout DSTECH v.4 (4.0, 30/09/2026), fixas no gerador.

`identificacao` e `cabecalho` são tabelas distintas e não devem ser fundidas.

## Seção

```json
{ "titulo": "3. Banco de dados", "nivel": 1, "quebraPagina": true, "blocos": [ … ] }
```

| Campo | Efeito |
|---|---|
| `titulo` | texto do heading |
| `nivel` | `1` (default) ou `2` |
| `quebraPagina` | `true` inicia a seção em página nova. Só em nível 1 |
| `blocos` | lista de blocos, na ordem |

Numerar os títulos manualmente (`1.`, `2.`, …) — o gerador não numera.

## Blocos

### `paragrafo`
```json
{ "tipo": "paragrafo", "texto": "…" }
```

### `subtitulo`
Heading 3 dentro da seção.
```json
{ "tipo": "subtitulo", "texto": "Consultas sobre TGFCAB" }
```

### `lista` / `numerada`
```json
{ "tipo": "lista", "itens": ["…", "…"] }
```
`numerada` reinicia em 1 a cada bloco.

### `tabela`
```json
{
  "tipo": "tabela",
  "colunas": ["Objeto", "Operação", "Média (ms)", "Referência (ms)"],
  "linhas": [["TGFCAB", "DELETE", "1.607", "350"]],
  "pesos": [3, 1.2, 1, 1],
  "aligns": [null, "center", "right", "right"],
  "boldCols": [0],
  "monoCols": [],
  "legenda": "Fonte: dml_stats, 01/05/2026 a 01/09/2026."
}
```

| Campo | Efeito |
|---|---|
| `pesos` | proporção das colunas. Sem isso, todas iguais. Ver **Largura de coluna** |
| `aligns` | `"center"`, `"right"` ou `null` por coluna |
| `boldCols` | índices em negrito |
| `monoCols` | índices em Consolas 9pt — para nome de objeto, código de erro, argumento |
| `legenda` | linha em itálico cinza abaixo. **Toda tabela de número precisa dizer a fonte e o período** |

Cabeçalho com fundo navy e texto branco; linhas ímpares em cinza. Automático. A
tabela sai com layout fixo, e a linha não se parte entre páginas.

**Célula com `\n` vira uma linha por item.** É como uma lista de objetos entra numa
coluna: empilhada, em vez de alargar a tabela inteira. Vale para qualquer coluna.

#### Largura de coluna

`pesos` são proporções da largura útil da página, que é de **9298 DXA**. A conta que
importa: cada célula gasta **240 DXA** com as próprias margens, e **20 DXA valem 1 pt**.
Uma coluna de 400 DXA tem 8 pt de texto útil, onde não cabe nem "10".

O Word só parte palavra no meio quando ela não cabe de jeito nenhum, e o estrago
(`Responsáv/el`, `Méd/ia`, um `10` empilhado como `1` e `0`) não aparece no JSON: só no
PDF. Por isso o gerador estima a largura na hora de gerar e **avisa no terminal** quando
um rótulo ou valor não cabe:

```
aviso: coluna "Origem" tem 44pt uteis e "Personalização" precisa de ~85pt.
```

O aviso não aborta a geração. Ele é para ser lido: ou a coluna cresce, ou o texto encurta.
Numa tabela de seis colunas, encurtar costuma ser a saída ("Cliente" e "Produto" dizem o
mesmo que "Personalização"). Gerar sem nenhum aviso é a meta.

Largura mínima prática, contando as margens: **560 DXA** para número de duas casas,
**940 DXA** para "Média", **1700 DXA** para "Responsável".

Nome qualificado, caminho e argumento recebem ponto de quebra invisível no ponto, na
barra, no sublinhado e na troca de minúscula para maiúscula, então quebram sozinhos e não
entram nessa conta. O cabeçalho fica de fora dessa ajuda de propósito: rótulo que não cabe
é erro de largura, e esconder isso com quebra invisível só adia o problema.

**A conferência final é no PDF, não no DOCX.** Exportar e olhar a página de cada tabela
grande. Um documento que passa no `validate.py` e sai torto passou nas duas checagens
automáticas e falhou na única que o cliente faz.

### `evidencia`
Trecho literal de log. Monoespaçado, fundo cinza, barra verde à esquerda.
```json
{
  "tipo": "evidencia",
  "linhas": [
    "2026-09-01 13:32:03,873 ERROR [stderr] (Financeiro:DataPager_7751…)",
    "java.lang.IllegalStateException: A pagina de dados 2 foi gerada, mas demorou muito a ser consumida"
  ],
  "legenda": "server.log — 01/09/2026 13:32:03"
}
```

Regras:
- **Copiar do log, sem reescrever.** Trecho editado deixa de ser evidência.
- Cortar linha longa em ~110 caracteres — não há refluxo, o excesso é aparado pela margem.
- No máximo ~8 linhas. Stacktrace inteiro vai para o anexo, não para o corpo.
- A legenda diz **arquivo e horário**. Sem isso, ninguém confere.

### `imagem`
Gráfico gerado por `scripts/gerar_graficos.py`. Caminho relativo ao JSON.
```json
{
  "tipo": "imagem",
  "arquivo": "graficos/02-dml-vs-referencia.png",
  "legenda": "Tempo médio medido por operação, contra a referência do checklist Sankhya. Fonte: estatísticas de comandos de banco, 4 meses."
}
```

A largura padrão é a área útil da página; a altura sai da proporção do próprio PNG,
lida do cabeçalho do arquivo. `larguraTwips` reduz um gráfico específico.

**A legenda é obrigatória** e diz fonte e período. Ela é o que resta quando o documento
é impresso em preto e branco, e é onde o leitor confere de onde veio o número.

Um bloco `achado` também aceita `grafico` com a mesma estrutura, renderizado depois do
trecho de log. Use quando o gráfico for a evidência daquele achado, não ilustração geral.

### `sql`
Script para o cliente copiar e executar. O texto vem **do arquivo**, nunca inline: a
seção existe para entregar o script que a skill mantém, e SQL digitado no JSON sai do
controle da regressão.

```json
{
  "tipo": "sql",
  "titulo": "Chaves estrangeiras sem índice",
  "arquivo": "../../.claude/skills/analise-performance/references/scripts-sql/oracle-indices-fk.sql",
  "responde": "Lista as colunas de chave estrangeira sem índice de apoio e cria o índice.",
  "aviso": "Altera estrutura de tabela. Executar em janela de manutenção, com retorno planejado.",
  "origem": "Checklist de problemas de performance — Service Desk Sankhya"
}
```

| Campo | Obrigatório | Conteúdo |
|---|---|---|
| `arquivo` | sim | caminho do `.sql`, relativo ao JSON ou absoluto. Arquivo ausente aborta a geração |
| `titulo` | não | vira Heading 3 |
| `responde` | não | uma frase sobre a saída do script. Sai do `catalogo.json` |
| `aviso` | não | caixa de atenção. **Obrigatório** quando `tipo` do catálogo é `ddl` ou `objeto` |
| `origem` | não | vai na linha de rodapé, junto ao nome do arquivo |

O renderizador escreve linha a linha em Consolas 8pt, sem refluxo e sem numeração de
linha: o cliente vai selecionar e copiar. Comentário de autoria no topo do `.sql` é
removido antes de entrar no documento.

**Script grande não é transcrito.** Acima de 120 linhas ou 12 KB, o bloco imprime as
primeiras linhas de comentário e diz que o arquivo segue anexo. `sp_WhoIsActive` tem
134 KB: transcrito, viram dezenas de páginas que ninguém copia da tela, e ~37 mil tokens
se alguém ler o arquivo em contexto.

**O caminho do arquivo não é escolhido a dedo.** Sai de
`evidencias.json['banco']['scripts']['aplicaveis'][].arquivo`, que o coletor já filtrou
pelo dialeto detectado. Montar o bloco a partir do nome que o analista lembra é como o
documento acaba entregando script do banco errado.

### `destaque`
Caixa cinza com barra verde. Para conclusão de seção, ressalva ou limitação.
```json
{ "tipo": "destaque", "titulo": "Limitação", "texto": "…" }
```
`titulo` default: `Observação`. Usar com parcimônia — três caixas por página anulam o
efeito de destaque.

### `achado`
A unidade do diagnóstico. Renderiza um Heading 2 com a severidade ao lado e os quatro
campos sempre na mesma ordem.

```json
{
  "tipo": "achado",
  "titulo": "Exclusões em TGFCAB muito acima do tempo de referência",
  "severidade": "alta",
  "evidencia": "Média de 1.607 ms por exclusão em 224 execuções, contra 350 ms de referência (+359%).",
  "impacto": "…",
  "causa": "…",
  "acao": "…",
  "trecho": ["…"],
  "legendaTrecho": "dml_stats — 01/09/2026",
  "tabela": { "colunas": [...], "linhas": [...] }
}
```

| Campo | Obrigatório | Conteúdo |
|---|---|---|
| `titulo` | sim | o que está errado, em linguagem de negócio |
| `severidade` | sim | `crítica` · `alta` · `média` · `baixa` |
| `evidencia` | sim | **o número medido e a fonte.** Sem número, não é achado |
| `impacto` | sim | o que o usuário sente, ou o risco corrido |
| `causa` | sim | hipótese, marcada como hipótese quando for |
| `acao` | sim | o próximo passo concreto e de quem é |
| `trecho` | não | linhas de log que sustentam o achado |
| `tabela` | não | números de apoio |

`impacto` e `causa` são coisas diferentes e ambos precisam existir. Achado sem impacto o
cliente desprioriza; achado sem causa ele não sabe a quem encaminhar.

## Seção do Monitor de Consultas — sem tipo de bloco novo

A seção 6 se monta com os blocos que já existem, nesta combinação:

| Subseção | Blocos |
|---|---|
| 6.1 método de pontuação | `destaque` (as quatro parcelas e as faixas) |
| 6.2 consultas ofensivas | `tabela` do ranking + `imagem` do gráfico de pontuação |
| 6.3 consultas com erro | `tabela` + `evidencia`, ou `paragrafo` quando não há erro |
| 6.4 pontos de atenção | `tabela` de três colunas: ponto, mostra, não prova |

A tabela do ranking pede `monoCols` na coluna dos objetos e `aligns` à direita nas colunas
numéricas. A pontuação entra como número, sem cor e sem ícone — a mesma regra da severidade
vale aqui.

Consulta de classe alta ou crítica ganha **também** um bloco `achado` na seção 5. O
`achado.evidencia` daquele bloco tem de trazer o número que o sustenta: execuções, média,
máximo e participação no tempo capturado.

**Nunca colocar valor de `Params:`** em `tabela.linhas`, em `evidencia.linhas` ou em
`achado.trecho`. O coletor não os guarda; o risco é alguém copiar do log bruto.

## Severidade — por que sem cor

O Modelo de Documento Padrão Sankhya 2026 não tem vermelho, âmbar ou verde de status; o verde
da marca é reservado a filete, barra e rótulo. Introduzir uma paleta de semáforo no DOCX quebraria o padrão
visual dos demais documentos do Delivery Service Tech e não sobrevive à impressão P&B.

A severidade aparece como texto ao lado do título e a ordenação do documento faz o resto:
**achados em ordem decrescente de severidade, sempre.** Se o cliente pedir sinalização
colorida, isso é decisão de padrão visual — não improvisar no documento.

## Campos que passam pelo `humanizer`

**Passam** (texto corrido, lido por pessoa):

- `subtitulo`
- todo `paragrafo.texto`
- todo `destaque.texto`
- `achado.impacto`, `achado.causa`, `achado.acao`
- `achado.titulo`
- itens de `lista` e `numerada`
- `tabela.legenda`

**Não passam** (reescrever corrompe o dado):

- `sql.arquivo` e o conteúdo do `.sql` — é comando, não prosa. `sql.responde` e
  `sql.aviso` passam
- `achado.evidencia` — carrega número e unidade
- texto de SQL vindo do monitor (`ofensivas[].sql`) — é comando, não prosa
- `monitor.atencao[].o_que_nao_prova` quando copiado literal: já está escrito para o leitor
- `evidencia.linhas` e `achado.trecho` — texto literal de log
- `tabela.colunas` e `tabela.linhas`
- `identificacao` e `cabecalho`
- nome de arquivo, objeto de banco, argumento de VM, código `ORA-`

Rodar o humanizer no JSON montado arrisca reescrever número e rótulo. **Humanizar o texto
antes de montar o JSON.**
