# Estrutura e conteúdo do documento

Detalhe operacional da redação. O `SKILL.md` traz só as regras que, se esquecidas,
produzem um documento errado; o resto está aqui.

## Ordem das seções

1. Sumário executivo — situação e a tabela dos gargalos principais
2. Ambiente analisado
3. Metodologia e fontes — inclui a caixa de limitações
4. Perfil de carga
5. Gargalos identificados — um bloco `achado` por gargalo, severidade decrescente
6. Monitor de Consultas — consultas ofensivas, erros e pontos de atenção
7. Configuração do servidor
8. Argumentos da máquina virtual em uso
9. Comparação com o pacote de referência
10. Recomendações — ação, objeto, responsável (pelo assunto), prioridade
11. Verificações complementares
12. Scripts para execução — o SQL de cada verificação, no dialeto detectado

Seções 4, 7, 8 e 9 saem quando não há o que dizer. A 6 sai **só quando o cliente não
mandou o pacote do Monitor de Consultas** — e nesse caso a ausência entra nas limitações,
porque é a única fonte que responde "qual SQL". A 12 sai quando nenhuma recomendação ou
verificação depende de script. As demais são obrigatórias, mesmo curtas: um diagnóstico
sem seção de limitações não é diagnóstico.

## Seção 5 — os achados

Um bloco `achado` por gargalo, com os quatro campos sempre na mesma ordem: evidência,
impacto, causa provável, ação. Ordem decrescente de severidade.

Agrupar sintomas que compartilham causa em um único achado. Dez linhas de log
diferentes que descrevem a mesma falha são um achado, não dez.

Quando um achado automático for descartado, e o descarte não for óbvio, registrá-lo com
severidade baixa e o motivo. É o que separa "não vimos" de "vimos e concluímos que não
é prioridade".

**O objeto entra na `evidencia` e volta na `acao`.** A `evidencia` diz onde a falha foi
medida: entidade, tabela, serviço, URI, classe e linha, com a contagem de cada um. A `acao`
repete o objeto que vai ser tocado, porque é ela que o responsável executa. Quando há mais
de um objeto, uma `tabela` de apoio no próprio achado lê melhor que uma lista dentro do
parágrafo. Como levantar o objeto: seção 2.1 do `SKILL.md` e `scripts/extrair_objetos.py`.

Quando a pilha fechar a causa, dizer que fechou. A skill trata causa como hipótese por
padrão, e por bom motivo; mas uma rotina executada sem transação chamando um método que
exige transação ativa não é hipótese, e escrever "provável" ali enfraquece um achado que
está provado. Achado com causa fechada muda de dono: vai para quem corrige, não para quem
investiga.

**Objeto que o pacote não nomeia não se inventa.** Falta de origem identificada é frase de
uma linha no achado, e a coleta que a resolveria vai para a seção 11.

O `acao` do achado nomeia o responsável, e usa a mesma tabela de critério das regras de
conteúdo. Achado e seção 10 não podem discordar sobre o dono: quem lê a seção 5 e depois
a 10 tem de encontrar o mesmo nome nos dois lugares.

## Seção 6 — Monitor de Consultas

Existe quando o pacote do monitor veio junto. Fonte: `consultar.py --o monitor`,
`--o monitor-atencao`, `--o monitor-erros`, `--o monitor-origens`. Limiares, pontuação e o
que cada evidência não prova: `catalogo-gargalos.md`, 2.6.

Quatro subseções, nesta ordem:

**6.1 Método de pontuação.** Um `destaque` com as quatro parcelas (peso no período,
lentidão unitária, repetição, cauda), as faixas e uma frase dizendo que a pontuação ordena
o trabalho e não aponta causa. Sem isso o cliente lê "78 pontos" como nota de gravidade
absoluta, e a primeira pergunta da reunião é de onde saiu o número.

**6.2 Consultas ofensivas.** Tabela do ranking — pontuação, classe, comando, objetos,
execuções, média, máximo, participação no tempo, origem — e o gráfico
`07-monitor-pontuacao.png`. O gráfico `08-monitor-faixas.png` entra quando a desproporção
entre faixas sustenta uma frase do texto ("0,02% das execuções consomem 11% do tempo").
`09-monitor-origens.png` entra quando a origem muda o destinatário da ação.

Consulta de pontuação alta ou crítica **também** vira bloco `achado` na seção 5, com
impacto e causa. A 6.2 é o ranking; a 5 é o diagnóstico. Não repetir o mesmo texto nos dois
lugares: na 6.2 fica a linha da tabela, na 5 o raciocínio.

**6.3 Consultas com erro.** Tabela com marcador, ocorrências, objetos e origem, mais um
bloco `evidencia` com a linha literal do log. Separar, sempre, as duas evidências: erro no
comando e requisição que terminou em erro não são a mesma coisa.

Sem erro no pacote, a subseção continua existindo, com uma frase: *"Não há marcador de erro
no log do monitor deste pacote"*, seguida do número de execuções originadas de requisição
que terminou em erro, quando houver. Omitir a subseção faz o leitor supor que ninguém olhou.

**6.4 Pontos de atenção.** Tabela de três colunas: ponto, o que a evidência mostra, o que
ela **não** prova. A terceira coluna não é enfeite — é o que impede a reunião de virar
"então falta índice". Os rótulos de contexto (execução em background) saem em frase à
parte, nunca na tabela de apontamentos.

**Janela.** O monitor não registra horário. O texto não pode sugerir que a janela do
monitor e a do `server.log` são a mesma; quando as duas fontes discordarem — monitor
benigno com `dml_stats` pesado, por exemplo — dizer que discordam e por quê.

## Seção 8 — argumentos em uso

Tabela com todos os argumentos que o ambiente carrega, de `wildfly.argumentos_cliente`
(`consultar.py --o args`): argumento, valor, o que faz.

A descrição de cada um sai de `argumentos-wildfly.md`. Argumento não catalogado entra
com a função em branco, nunca com descrição inventada.

Agrupar por assunto — memória e coletor, persistência e banco, servidor e rede, jobs —
em vez de ordem alfabética. Serve a dois leitores: quem vai mexer na configuração e quem
quer saber o que está ligado no servidor.

Endereço, caminho e credencial entram abreviados ou omitidos. `-Dsnk.auth.folder` com o
caminho completo não agrega e expõe a topologia do cliente.

## Seção 9 — comparação com o pacote de referência

De `consultar.py --o wildfly` e `--o drivers`. Uma tabela por lista, e **as listas não
se misturam**:

- `ausentes` e `divergentes` são apontamentos;
- `ausentes_condicionais` viram nota de rodapé, ou saem: são ausências corretas;
- `dimensionamento` **não é apontamento** — ver `baseline-wildfly23.md`;
- `extras` pedem leitura caso a caso; muitos são funcionalidade legítima.

Drivers: classe, versão do cliente, versão do baseline, versão do banco, situação.
Regras em `drivers-jdbc.md`.

**A recomendação de subir para o WildFly 23 nunca abre a lista de recomendações.** É
substituição de instalação, com janela de parada e plano de retorno, e não acelera uma
procedure que leva 26 segundos. No topo, ela faz o cliente acreditar que resolve tudo, e
a frustração posterior desacredita a análise inteira.

## Seção 12 — scripts para execução

Existe porque a seção 11 manda o cliente executar `oracle-indices-fk.sql` e o cliente não
tem esse arquivo. Recomendação que aponta para um nome de arquivo que só a skill conhece
não é executável: ela vira uma pergunta no e-mail seguinte.

Fonte: `consultar.py --o banco`. O coletor já resolveu o dialeto e já filtrou o catálogo;
esta seção só transcreve. Um bloco `sql` por script, na ordem em que a seção 11 os citou.

**Abrir com o dialeto e a evidência dele.** Um parágrafo dizendo qual banco foi
identificado, por qual fonte e com que evidência. O cliente que roda um script do dialeto
errado recebe erro de sintaxe e conclui que a análise foi feita no ar.

Regras que não podem ser esquecidas:

- **Nunca script do outro dialeto.** Ambiente Oracle recebe os cinco scripts de Oracle e
  nenhum de SQL Server. A lista de drivers carregados não decide isso — num pacote
  observado, um ambiente Oracle tinha o driver de SQL Server no deploy;
- **dialeto não identificado, seção não existe.** Sem URL de datasource, banner no log ou
  driver único, o pacote não responde qual banco está em uso. Nesse caso a seção 12 sai e
  a impossibilidade entra nas limitações, com o pedido do `mge-ds.xml`;
- **script que altera estrutura vem com aviso.** `tipo` `ddl` ou `objeto` no catálogo
  exige o campo `aviso` no bloco, com janela de manutenção e retorno planejado. O de
  índices de chave estrangeira em Oracle cria objeto e executa DDL; o de SQL Server
  apenas gera os comandos, e isso precisa estar dito;
- **script autoral vem marcado.** `origem: "skill"` no catálogo significa que o script não
  passou pelo Service Desk. A linha de origem do bloco diz isso, e a frase de abertura da
  seção repete;
- **lacuna é registrada, não escondida.** Verificação da seção 11 sem script para o
  dialeto entra numa lista curta ao final, com o motivo. Omitir faz o leitor supor que a
  verificação foi esquecida.

## Regras de conteúdo

- **Linguagem funcional.** "Tabela de cabeçalho de nota" no texto corrido; o nome técnico
  fica na tabela e na evidência.
- **O dialeto do banco é decidido uma vez, no bloco `banco`.** Nenhuma seção do documento
  volta a inferir banco a partir de driver carregado ou de código `ORA-`.
- **Nunca citar o banco por nome** no corpo. "Banco de dados", não "Oracle". Exceção:
  o código `ORA-nnnnn` é evidência literal e vai como está.
- **Trecho de log é literal.** Copiar, nunca reescrever. Cortar em ~110 caracteres.
- **Não expor credencial.** A URL do datasource carrega host, porta e SID.
- **Responsável explícito** em cada recomendação. Recomendação sem dono não é executada,
  e dono errado é pior que dono nenhum: a ação volta semanas depois, sem ter saído do
  lugar. O critério é o **assunto**, não quem operou a máquina:

  | Assunto | Responsável |
  |---|---|
  | Parâmetro de infraestrutura, argumento da máquina virtual, servidor de aplicações, versão de Java, driver, rede, disco | TI do cliente |
  | Qualquer coisa de aplicação: código do produto, serviço, entidade, dicionário, publicação de módulo, rotina agendada, integração | Sankhya |
  | Índice, plano de execução, estatística, trigger, bloqueio, objeto de banco | DBA |
  | Código de módulo de personalização ou de integração escrito fora do produto | Autor do módulo |
  | Conferência ou correção de dado de negócio | Área de negócio do cliente (departamento pessoal, fiscal, compras) |

  A dúvida some com uma pergunta: **se a ação fosse feita, o que mudaria?** Um arquivo de
  configuração do servidor muda, é TI do cliente. Uma classe, um serviço, um metadado ou
  um comportamento do produto muda, é Sankhya, mesmo que quem publique seja o cliente.
  Republicar módulo e reexecutar migração de dicionário são assunto de aplicação: o fato
  de a operação rodar no servidor não os torna infraestrutura.

  Dono duplo só quando a ação tem mesmo duas metades de donos diferentes, e a redação diz
  qual é qual: remover o agente de telemetria é argumento da máquina virtual e é do
  cliente, mas a disponibilidade do coletor é de quem o hospeda.
- **Objeto explícito** em cada recomendação, na coluna própria da tabela da seção 10:
  classe, serviço, entidade, tabela, procedure, módulo, URI, argumento ou script, com o
  tipo junto. Recomendação sem objeto tem dono e não tem endereço, e volta como pergunta
  no e-mail seguinte. Ação que depende de coleta nova declara isso na coluna, em vez de
  deixá-la vazia. A mesma coluna entra na tabela de gargalos do sumário executivo,
  resumida ao objeto principal: quem lê só a primeira página sai sabendo onde mexer.
- **Sem horas.** Aprovadas as ações, o orçamento é de `sankhya-estimativa-planejador` e
  `orcamento-horas-docx`.

## Gráficos

Regras completas e justificativa no cabeçalho de `scripts/gerar_graficos.py`. Em resumo:

- cada gráfico sustenta uma frase do documento; sem isso, é ilustração e enfraquece o texto;
- **nunca dois eixos y no mesmo plano** — duas escalas viram dois painéis;
- série única ou ênfase, nunca paleta categórica (a paleta do Brandbook reprova nas
  checagens categóricas; a saída é a forma, não uma cor de fora da marca);
- verde só como linha de referência, sempre com rótulo em texto;
- legenda quando há dois grupos; identidade nunca só na cor;
- rótulo direto no extremo, não em todo ponto.

Gráfico com uma barra e uma ocorrência não é gráfico: a tabela diz o mesmo em menos
espaço e sem sugerir volume. O gerador já recusa o gráfico de erros abaixo de três
consultas distintas ou dez ocorrências; a mesma régua vale para o que for montado à mão.

Depois de gerar, **abrir os PNG e olhar**. Legenda sobre barra, rótulo estourando margem
e subtítulo colidindo com título já aconteceram aqui, e nenhum aparece no código.

## Dados pessoais

O `.ald` registra nome de usuário e IP. No documento:

- usuário entra por função ou volume ("o usuário mais ativo abriu 1.284 telas"), não por
  nome, salvo quando o achado depende de identificar a pessoa e o usuário pediu;
- IP entra só quando o achado é sobre origem de acesso;
- `sessionId` nunca.

Do Monitor de Consultas, **valor de parâmetro não entra em lugar nenhum** — nem na tabela,
nem no bloco de evidência, nem parafraseado. É dado de negócio do cliente (documento, valor
de título, nome de pessoa); o coletor guarda apenas a quantidade de parâmetros. O texto do
SQL entra com os parâmetros como `?` e os literais colapsados, exatamente como o coletor os
devolve.

O `evidencias.json` guarda esses dados porque a análise precisa deles. É insumo interno:
ao cliente vai o DOCX, não o JSON.
