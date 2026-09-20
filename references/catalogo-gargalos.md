# Catálogo de gargalos

Regras de leitura das evidências. Cada entrada tem **sinal** (o que aparece no pacote),
**limiar** (quando vira achado), **causa provável** e **o que a evidência não prova** —
esta última coluna existe porque diagnóstico de performance erra principalmente por
concluir demais a partir de pouco.

Fonte dos limiares oficiais: *Checklist de problemas de performance — Service Desk*
(Sankhya). Onde não há limiar oficial, o corte está marcado como **convenção da skill** e
deve ser apresentado como tal, nunca como número oficial da Sankhya.

## Como classificar o tipo de lentidão

O checklist organiza o atendimento em três tipos. Enquadrar o caso é o primeiro passo,
porque muda a lista de hipóteses:

| Tipo | Sintoma | Onde olhar primeiro |
|---|---|---|
| **Generalizada** | todos os usuários, todas as rotinas | máquina, banco, heap, pool, rede |
| **Localizada** | uma tela, rotina ou módulo | consulta lenta, personalização, parametrização |
| **Em horários específicos** | some depois de um tempo | jobs, backup, integração, relatório agendado |

O pacote de log responde parcialmente: `.ald` mostra se a carga se concentra em poucas
telas (indício de localizada) e a série por hora mostra se os erros se concentram numa
janela (indício de horário específico). O que ele não responde é o **sintoma percebido** —
por isso o questionário de lentidão (`questionario-lentidao.md`) continua sendo insumo.

---

## 1. Memória e JVM

### 1.1 Xms diferente de Xmx
**Sinal:** `Argumentos da VM` com `-Xms2048m -Xmx5012m`.
**Limiar:** qualquer diferença. Regra explícita do checklist: "a memória deve estar
configurada com o mesmo valor para mínimo e máximo".
**Causa:** heap cresce sob carga; a expansão acontece justamente no pico.
**Não prova:** que houve pausa perceptível. É desvio de configuração, não incidente.

### 1.2 Heap perto do teto no momento da coleta
**Sinal:** `Memoria Heap: 4257 / 4995 MB` (85%).
**Limiar (convenção):** ≥85% média · ≥92% alta.
**Causa:** heap subdimensionada para a carga, ou retenção de objetos.
**Não prova:** vazamento. É **uma amostra**, tirada no instante da coleta — pode ser o
estado normal logo antes de uma coleta de lixo. Só o log de GC ou uma série de amostras
sustenta a palavra "vazamento".

**Não vale nada quando Xms = Xmx.** A máquina virtual reserva a heap inteira na subida, e
a razão dá 100% em todo pacote com essa configuração — que é justamente a que o checklist
recomenda. Num pacote real isso virou "heap a 100%, severidade alta" com o coletor de lixo
gastando 0,09% do tempo. O coletor hoje descarta o achado nesse caso, e quem mede pressão
de memória é o item 1.7.

### 1.7 Tempo em coleta de lixo
**Sinal:** `Tempo gasto com GC: 0.09% | Recomendado: Maximo 2%`, no bloco de diagnóstico
do comentário do zip. Recorte: `consultar.py --o diagnostico`.
**Limiar:** o do próprio pacote — 2%. Convenção da skill para severidade: ≥2% média,
≥5% alta.
**Por que é a medida boa:** vem medida sobre a vida do processo, não sobre um instante, e
já traz o limite ao lado. É o que desmente ou confirma o item 1.2.
**Não prova:** a duração de cada pausa. 2% acumulado pode ser mil pausas curtas ou dez
longas, e só a segunda o usuário sente. Para isso, habilitar `-Xloggc:` e recoletar.

### 1.3 Heap muito grande
**Sinal:** Xmx acima de ~8 GB com CMS ou sem G1 ajustado.
**Causa:** o checklist alerta que "valores de memória muito altos podem ocasionar
congelamento durante a limpeza da heap". Heap grande com coletor antigo = pausa longa.
**Não prova:** que a pausa ocorreu. Sem log de GC, é hipótese.

### 1.4 Coletor CMS
**Sinal:** `-XX:+UseConcMarkSweepGC`.
**Causa:** CMS foi descontinuado a partir do Java 9 e fragmenta em heap grande. O material
de argumentos da Sankhya indica **G1** (`-XX:+UseG1GC`) com `MaxGCPauseMillis`,
`InitiatingHeapOccupancyPercent=30` e `G1ReservePercent`.
**Cuidado:** trocar coletor em produção muda o perfil de pausa. Recomendar com janela de
validação, nunca como ajuste trivial.

### 1.5 OutOfMemoryError / GC overhead limit exceeded
**Sinal:** as strings no log.
**Limiar:** **uma** ocorrência já é crítica.
**Causa:** heap insuficiente ou retenção. Após um OOM, threads ficam em estado indefinido
e o servidor deixa de ser confiável até reiniciar.
**Leitura correta:** isso é **indisponibilidade**, não lentidão. Separar das demais no
documento.

### 1.6 Sem `-XX:+HeapDumpOnOutOfMemoryError`
**Sinal:** argumento ausente.
**Consequência:** um estouro futuro não deixa evidência analisável. Recomendar sempre
junto com `-XX:HeapDumpPath` apontando para disco com espaço.

---

## 2. Banco de dados — DML

Base: `dml_stats`. Tempo médio = `TEMPO_TOTAL_MS / EXECUCOES`.

### 2.1 Objetos com limiar oficial

| Objeto | Operação | Referência |
|---|---|---:|
| TGFCAB | INSERT | 200 ms |
| TGFCAB | UPDATE | 100 ms |
| TGFCAB | DELETE | 350 ms |
| TGFITE | INSERT | 200 ms |
| TGFITE | UPDATE | 100 ms |
| TGFITE | DELETE | 200 ms |
| TGFFIN | INSERT | 150 ms |
| TGFFIN | UPDATE | 100 ms |
| TGFFIN | DELETE | 200 ms |
| STP_CONFIRMANOTA2 | STP | 300 ms |
| STP_NUMERAR_NOTA2 | STP | 200 ms |
| STP_SET_SESSION / STP_SET_SESSION2 | STP | 10 ms |

**Tolerância: +20%.** O checklist é explícito: "existindo uma pequena elevação de até 20%
destes valores, podem ser considerados [aceitáveis]", e que os valores "podem aumentar em
caso de alto volume de personalizações, principalmente nas tabelas TGFCAB e TGFITE".

**Causa provável de excesso:** o checklist aponta primeiro para **objetos personalizados
sobre a tabela** — triggers, eventos programáveis, regras. Só depois infraestrutura.

**Não prova:** qual personalização. O pacote não lista triggers. O caminho é rodar
`scripts-sql/oracle-busca-textual-objetos.sql` no ambiente do cliente.

### 2.2 DELETE lento
O checklist destaca DELETE: "os comandos de exclusão de dados geralmente são causadores de
contenção". DELETE acima do limiar merece seção própria mesmo quando o excesso percentual
é menor que o de um INSERT.

### 2.3 Procedure personalizada custosa
**Sinal:** objeto `STP_*` fora da nomenclatura padrão (sufixo com nome do cliente,
prefixo `AD_`) com tempo médio alto.
**Limiar (convenção):** média ≥1.000 ms **e** tempo total ≥60 s no período. Os dois juntos,
para não promover a achado uma procedure lenta que roda uma vez por mês.
**Causa:** rotina personalizada sem índice adequado, cursor linha a linha, ou processando
volume maior do que quando foi escrita.
**Ação:** o checklist manda direcionar ao autor da customização, não ao suporte do produto.

### 2.4 Objeto com muitas execuções
**Sinal:** contagem de execuções muito acima dos demais (ex.: `STP_SET_SESSION2` com dezenas
de milhões).
**Leitura:** média baixa com volume gigante ainda soma. Um objeto com média de 1 ms e 88
milhões de execuções consome mais tempo total que uma procedure de 26 s rodando 371 vezes.
**Ordenar o ranking por tempo total, não por média** — e mostrar as duas colunas, senão o
leitor conclui errado.

### 2.5 Índices ausentes em chave estrangeira
**Sinal:** não aparece no pacote. É verificação prévia obrigatória do checklist em Oracle.
**Ação:** `scripts-sql/oracle-indices-fk.sql`. FK sem índice causa contenção em cascata.
Entra como recomendação de verificação, nunca como achado — o pacote não permite afirmar.

---

## 2.6 Monitor de Consultas — consultas ofensivas

Base: pacote do Monitor de Consultas (`Monitor_Consulta.log` + `Monitor_Processos.log`).
Recorte: `consultar.py --o monitor`. Formato das fontes em `fontes-pacote-log.md`.

Diferença em relação a `dml_stats`: ali o dado é agregado **por objeto**, aqui é **por
consulta**, com o texto do comando e a pilha de quem chamou. É a única fonte do pacote que
responde "qual SQL" e "quem disparou".

### Pontuação de ofensa (0 a 100)

Quatro parcelas somadas, todas no JSON em `ofensivas[].parcelas`:

| Parcela | Faixa | O que mede |
|---|---:|---|
| peso no período | 0–40 | tempo total da consulta ÷ tempo total capturado |
| lentidão unitária | 0–30 | média por execução, log a partir de 100 ms (1 s = 15, 10 s = 30) |
| repetição | 0–20 | execuções em escala log (100 = 10, 10.000 = 20) |
| cauda | 0–10 | p95 ≥ 5 s = 10 · máximo ≥ 5 s = 7 · máximo ≥ 1 s = 4 |

Faixas: **crítica ≥ 70 · alta 50–69 · média 30–49 · baixa < 30.**

A pontuação existe para **ordenar o trabalho**, e é isso que ela pode fazer. Ela não
distingue falta de índice de estatística velha, nem de volume legítimo — as três produzem a
mesma pontuação. Quem separa é o plano de execução, que não está no pacote.

Escrever "consulta com 78 pontos de ofensa" é correto. Escrever "consulta sem índice" a
partir da pontuação é inventar causa.

### Consultas com erro

Duas evidências diferentes, e o documento não as mistura:

| Evidência | O que prova | O que não prova |
|---|---|---|
| marcador no bloco (`ORA-nnnnn`, `SQLException`, `Msg nnnn, Level n`) | a consulta falhou no banco | não prova impacto no usuário; pode ser tratada pela rotina |
| `SendErrorPageHandler` / `MGEModelException` na pilha | a requisição terminou em erro | **não prova que a consulta falhou** — ela pode ter executado bem e a requisição falhado depois |

Erro de banco em consulta é **defeito, não lentidão**: precede qualquer ajuste de
performance na lista de recomendações, e o dono é o autor do objeto.

Quando não há marcador de erro, a subseção diz isso com essas palavras. Omitir a subseção
faz o leitor supor que ninguém olhou.

### Pontos de atenção detectáveis no texto do comando

Cada rótulo vem do `ATENCAO_CATALOGO` do coletor, e cada um carrega a própria coluna "não
prova" no JSON — `consultar.py --o monitor-atencao` imprime as três colunas juntas.

| Rótulo | Sinal |
|---|---|
| `sem_filtro` | SELECT/UPDATE/DELETE sem `WHERE` (fora de `DUAL` e sequence) |
| `for_update` | bloqueio explícito de linha |
| `funcao_no_filtro` | `UPPER`, `TRUNC`, `TO_CHAR`, `NVL`… aplicada à coluna filtrada |
| `like_curinga_inicial` | `LIKE '%valor'` |
| `subconsulta_no_filtro` | `IN (SELECT …)` / `EXISTS (SELECT …)` |
| `distinct_com_juncao` | `SELECT DISTINCT` sobre junção |
| `projecao_larga` | 50 ou mais colunas na projeção |
| `select_estrela` | `SELECT *` |
| `objeto_personalizado` | `FROM/JOIN/UPDATE AD_*`, procedure `STP_AD_*` |
| `origem_personalizada` | pilha parte de pacote fora de `br.com.sankhya` |
| `origem_em_script` | pilha passa pelo motor de script: evento programável / regra |
| `suspeita_n_mais_1` | ≥100 execuções da mesma consulta com média ≤50 ms |

`execucao_em_background` é **contexto, não apontamento**, e sai numa lista separada
(`contexto` no JSON). Num pacote colhido durante uma importação, ele marca quase todas as
consultas: promovê-lo a ponto de atenção abre o relatório com um não-defeito.

Os rótulos são a **união** das execuções daquela consulta: `origem_personalizada` quer dizer
"ao menos uma execução veio de código personalizado", não "toda execução veio".

### O que a fonte não permite

- **Não há horário.** O bloco não tem timestamp e o `##ID_n##` é sequencial. Não cruzar a
  janela do monitor com o pico de erro do `server.log` como se fossem a mesma janela —
  a sobreposição se pergunta a quem coletou.
- **Não há linhas retornadas.** Consulta de 3 ms que devolve 200 mil linhas passa por barata.
- **A janela é curta.** Monitor ligado por minutos não observa a rotina noturna. Resultado
  benigno do monitor não contradiz `dml_stats` nem `server.log`: fala de outra janela. Quando
  as duas fontes discordam, o documento **diz que discordam** e explica por quê.

---

## 3. Banco de dados — erros

| Código | Leitura | Severidade |
|---|---|---|
| `ORA-00060` | deadlock; contenção entre sessões | alta |
| `ORA-01013` | operação cancelada — tipicamente timeout de query | alta |
| `ORA-04031` | shared pool sem memória | alta, DBA |
| `ORA-12516` | processos do Oracle esgotados | alta, DBA |
| `ORA-00257` | archive log cheio | alta, DBA |
| `ORA-01555` | snapshot too old; undo insuficiente | alta, DBA |
| `ORA-00054` | recurso ocupado; lock não liberado | média |
| `ORA-00936` | SQL malformado, quase sempre de personalização | média |
| `ORA-28000` / `28001` | conta bloqueada / senha expirada | operacional |

O checklist trata explicitamente `ORA-00060` e `ORA-01013` como relacionados a lentidão.
Em SQL Server, os equivalentes são as mensagens de deadlock e timeout.

**Cuidado com contagem:** um único incidente gera o mesmo `ORA-` em várias linhas
(`Caused by`, mensagem original, wrapper). Contar linhas superestima. Reportar ocorrências
**e** a janela de tempo em que aconteceram.

---

## 4. Pool de conexões

### 4.1 Pool saturado
**Sinal:** série do `conn-stats` contra `max-pool-size` do `mge-ds.xml`.
**Limiar (convenção):** pico ≥80% do máximo = média · ≥95% = alta.
**Causa:** concorrência acima do dimensionado, ou conexão retida por rotina longa.
**Efeito no usuário:** espera por conexão livre. Não gera erro no log — é lentidão
silenciosa, e por isso costuma ser diagnosticada errado.
**Referência do checklist:** "verificar se o número de conexões concomitantes está alto,
chegando próximo da quantidade máxima do pool de conexões".

### 4.2 Pool esgotado
**Sinal:** `IJ000453`, `No ManagedConnections available`, `IJ000655`.
**Limiar:** qualquer ocorrência é crítica.

### 4.3 Conexão fechada em uso
**Sinal:** `Closed Connection`, `ORA-17008`.
**Causa:** conexão morta pelo banco ou por firewall e devolvida ao pool sem validação.
**Ação:** revisar validação de conexão do datasource. Atenção: `-Djape.check.is.valid.connection=false`
desliga a checagem `SELECT FROM DUAL` — ganha desempenho e perde essa proteção.

---

## 5. Timeouts

O sistema tem **três** timeouts distintos, e confundi-los leva a ajuste errado:

| Timeout | Argumento | Quando estoura |
|---|---|---|
| **Query** | `-Djape.global.query.timeout` (segundos) | uma consulta isolada demora demais |
| **Sessão** | `-Djape.session.timeout` (ms) | a sessão JAPE fica aberta além do limite |
| **Transação** | Narayana / WildFly | o conjunto da rotina excede o limite |

**Leitura do checklist:** timeout de sessão ou transação frequentemente ocorre com
consultas **rápidas** — "pode ser que elas estejam rápidas, mas a rotina executa milhares
de consultas de uma só vez". Concluir "consulta lenta" a partir de timeout de transação é
o erro clássico.

`SocketTimeoutException` é outra coisa: chamada externa sem resposta (SEFAZ, e-mail,
integração). Não é lentidão do ERP.

---

## 6. Erros e ruído no log

### 6.1 Proporção de erro
**Limiar (convenção):** ≥5% das entradas com cabeçalho = média · ≥15% = alta.
**Efeito:** além de esconder o evento relevante, log em volume alto custa IO de disco no
mesmo servidor da aplicação.
**Referência:** o checklist manda procurar "ocorrências repetidas de mensagens no log" e
distinguir erro de regra do cliente (ele resolve) de erro de sistema (vai para DBA/suporte).

### 6.2 Assinatura recorrente
Agrupar por classe da exceção + mensagem **normalizada** (números, ids e datas trocados por
`#`). Sem normalizar, a mesma falha vira centenas de assinaturas distintas.
Reportar: ocorrências, primeira e última aparição, e uma linha de amostra.

### 6.3 `DataPager … demorou muito a ser consumida`
**Causa:** o servidor gerou a página de dados e o cliente não a consumiu no prazo.
Aponta para consulta que devolve volume grande — tela sem filtro adequado, grade sem
paginação efetiva — ou rede lenta entre estação e servidor.
**Pista útil:** o nome da thread carrega a tela (`Financeiro:DataPager_…`,
`TimContratoVendaLote:DataPager_…`). Dá para nomear a rotina afetada.

---

## 6.4 Ciclo de vida do servidor

Recorte: `consultar.py --o ciclo`. Quatro sinais que não dependem de volume de usuário, e
por isso aparecem igual em pacote de instância ociosa e de produção.

### 6.4.1 Subida demorada ou com erro
**Sinal:** `WFLYSRV0026 ... started (with errors) in 361666ms`.
**Limiar (convenção):** ≥120 s média. Marca `(with errors)` é achado independente do tempo.
**Leitura:** o tempo de subida define a janela mínima de manutenção.
**Cuidado:** o `total` de serviços inclui os `lazy, passive or on-demand`, que nunca
iniciam. **Não subtrair** de `iniciados` para achar os falhos — num pacote real a
subtração dava 534 contra os 36 declarados na própria linha.

### 6.4.2 Componentes que não subiram
**Sinal:** bloco `WFLYCTL0186: Services which failed to start`.
**Limiar:** qualquer um. Componente que não sobe é rotina fora do ar.
**Causa provável:** contexto web publicado duas vezes (`WFLYUT0105: Host and context path
are occupied`), ou serviço externo indisponível no instante da subida.
**Leitura:** o usuário relata isso como lentidão, porque a tela nunca abre.
**Não prova:** que segue fora do ar. Num pacote observado a primeira subida teve 36 falhos
e a segunda 6 — o resultado depende da ordem, e muda a cada reinício.

### 6.4.3 Threads não encerradas na republicação
**Sinal:** `Erro ao interromper thread`, junto a `WFLYSRV0016: Replaced deployment`.
**Limiar:** qualquer ocorrência, porque o efeito é acumulado.
**Causa:** thread órfã mantém viva a referência ao carregador de classes do módulo antigo,
e com ele todas as classes dele. A memória permanente cresce a cada republicação.
**Não prova:** estouro de metaspace. Prova retenção; o estouro depende de quantas
republicações couberem antes do próximo reinício.

### 6.4.4 Falha de script de migração
**Sinal:** `Erro na execução do script` ou `ScriptMigrationProcessor` em nível ERROR,
com o módulo no prefixo `[modulo - ddmigration]`.
**Limiar (convenção):** ≥50 alta, abaixo disso média.
**Causa:** script sem verificação de estado, chamado a cada subida. Os códigos ORA típicos
são de objeto já existente (`ORA-01451`, `ORA-01430`, `ORA-00957`, `ORA-00955`).
`ORA-00054` é diferente e pior: a alteração foi abandonada por tabela ocupada.
**Cuidado:** `ScriptMigrationProcessor` sozinho **não** serve de gatilho. Esse logger emite
milhares de linhas INFO de progresso, e contá-las deu 2.194 num pacote onde as falhas reais
eram 222.
**Ação:** encaminhar por origem — módulo de produto para a Sankhya, módulo com sufixo do
cliente para o autor da personalização.

## 6.5 CPU por família de thread

**Sinal:** `consultar.py --o cpu`, sobre o campo `cpu=` de cada thread do dump.
**Limiar (convenção):** infraestrutura ≥40% com atendimento de requisição <5%.
**Leitura:** num pacote real, cluster em memória e varredura de deploy somavam 44,5% da
CPU do processo, contra 0,02% nas threads de requisição. É custo fixo: em produção ele se
soma à carga real e reduz a folga no pico.
**Dois denominadores, e confundi-los muda a conclusão:** `%vivas` é sobre as threads
presentes no dump; `%proc` é sobre a CPU que o processo consumiu desde que subiu, que só
existe quando o pacote traz o bloco de diagnóstico. Dizer qual está em uso, sempre.
**Não prova:** taxa. `cpu=` é tempo acumulado na vida de cada thread. Thread de requisição
é curta e morre, então a fatia dela é **piso**, não medida. Thread de infraestrutura é
singleton que vive com o processo, e para essa o número é sólido.
**Não prova** tampouco que desligar a varredura resolve lentidão: ela libera CPU, e se a
CPU não era o gargalo, o usuário não sente diferença.

## 7. Threads

### 7.1 Threads bloqueadas
**Limiar (convenção):** ≥5 em `BLOCKED` no dump = média · ≥15 = alta.
**Não prova:** contenção sustentada. **É uma foto.** Usar como corroboração de um sinal do
log, e dizer no documento que se trata de um instante.

### 7.2 Pool de trabalho saturado
**Sinal:** muitas threads `default task-N` todas ocupadas.
**Causa:** requisições presas esperando banco ou serviço externo. O sintoma é o servidor
"não responder" sem consumir CPU.

### 7.3 CPU concentrada
**Sinal:** poucas threads com `cpu=` muito acima das demais.
**Uso:** identificar a rotina que consome processamento. A pilha dá o caminho da classe.

---

## 8. Jobs e ações agendadas

**Sinal:** linhas `Tempo execucao: N ms` e a distribuição de erro por hora.
**Leitura:** job pesado concentrado em horário de operação é a explicação mais comum de
"lentidão em horários específicos".
**Verificar nos argumentos:** `-Dsankhyaw.schedule.disable=true` (nenhum job roda) e
`-Dsankhyaw.only.jobs=` (só os listados rodam). Ambos silenciosos — o cliente não percebe
que a rotina simplesmente não executa.
**Verificar no parâmetro:** `SERVERHOSTSCHED` define onde os jobs rodam; vazio = local,
IP = tudo naquele servidor, `IP:NomeDoJob` = só os listados.
**Tabelas para checar no ambiente:** `TSIARF` (relatórios agendados), `TSIAAG` (ações
agendadas), `TGFTAG` (tarefas), `TSICND` (consolidador).

---

## 8.1 Versão do servidor de aplicações e drivers

Detalhes em `baseline-wildfly23.md` e `drivers-jdbc.md`. Resumo do que vira achado:

| Sinal | Severidade | Cuidado |
|---|---|---|
| WildFly anterior à 23 | média | é substituição de instalação, não ajuste. Nunca no topo da lista: trocar o servidor não acelera procedure lenta |
| Argumento do baseline ausente | média se atinge coletor, codificação ou commit; baixa nos demais | parte dos argumentos do baseline depende de banco ou sistema operacional que o cliente não usa |
| `-Xms` / `-Xmx` diferentes do baseline | **não é achado** | o baseline traz valores de instalação, não de porte. O achado em memória é mínimo diferente de máximo, uso no teto, ou coletor inadequado |
| Driver atrás da versão do baseline | baixa | higiene. Afirmar que resolve gargalo de banco é erro de leitura |
| jTDS em uso | média | para SQL Server, o recomendado é o driver oficial da Microsoft. A troca muda a URL de conexão e pede validação de tipo de dado e fuso |
| Mais de um driver carregado | baixa | limpeza, sem ganho mensurável |
| Módulo com JAR inválido | média | indica migração antiga incompleta |
| Driver mais antigo que o banco | média | perde recurso e pode falhar em tipo de dado novo |

A versão do banco só entra quando o banner aparece no log. Sem ele, a comparação
driver/banco fica como verificação, e a versão do banco **não** se infere da versão do driver.

## 9. Configuração do WildFly

Desvios que valem menção quando presentes:

| Item | Esperado | Efeito do desvio |
|---|---|---|
| `Xms` = `Xmx` | iguais | expansão de heap sob carga |
| GC | G1 em heap grande | pausa longa com CMS |
| `HeapDumpOnOutOfMemoryError` | presente | sem evidência após estouro |
| `jape.global.query.timeout` | compatível com as rotinas longas | timeout indevido ou consulta eterna |
| `jape.session.timeout` | idem | sessão derrubada no meio da rotina |
| `max-pool-size` | acima da concorrência observada | espera por conexão |
| Instâncias TESTE/TREINA | paradas quando sem uso | concorrem por CPU e memória com produção |
| `epoll.hang.timeout` | presente em ambiente com trava de IO | travas de IO não detectadas |

O checklist pede explicitamente que os serviços de TESTE e TREINA estejam parados quando
não estiverem em uso — vale checar se há mais de uma instância no mesmo servidor.

---

## 10. Fora do alcance do pacote

Nunca afirmar sem a fonte. Quando a hipótese depender destes itens, ela vai para
"recomendação de verificação", com o comando ou script correspondente:

| Pergunta | Como verificar | Referência |
|---|---|---|
| CPU acima de 80%? | `top` / Gerenciador de Tarefas | checklist, item c |
| Memória do SO / swap? | `free -m` / Gerenciador de Tarefas | item d |
| Rede entre app e banco? | `ping -s 1024` — média até **0,5 ms** em rede 10/100/1000 | item e |
| Disco? | `winsat disk` / `dd` — mínimo **120 MB/s** sequencial | item f |
| Sessões ativas no banco? | `scripts-sql/oracle-sessoes-ativas.sql` | item g |
| Bloqueios longos? | `scripts-sql/oracle-bloqueios.sql` | item i |
| Estatísticas desatualizadas? | `scripts-sql/oracle-estatisticas.sql` | — |
| FK sem índice? | `scripts-sql/oracle-indices-fk.sql` | verificação inicial |
| Sessão do banco ↔ usuário do ERP? | `scripts-sql/sqlserver-2-sp_WhoIsActive_Skw2.sql` | SQL Server |
| Snapshot Isolation / Read Committed Snapshot? | consulta de configuração da base | verificação inicial, SQL Server |
| Lock Escalation e AllowPageLocks? | esperado `DISABLE` e `FALSE` | verificação inicial, SQL Server |
| Consulta lenta com o SQL? | pacote do Monitor de Consultas — coletado e pontuado automaticamente (2.6); sem o pacote, não é observável | lentidão localizada, item c |

---

## Severidade

| Nível | Critério |
|---|---|
| **Crítica** | indisponibilidade ou perda de dados: OOM, GC overhead, pool esgotado |
| **Alta** | degradação sentida pelo usuário com evidência direta e recorrente |
| **Média** | desvio de configuração ou degradação pontual |
| **Baixa** | boa prática não atendida, sem efeito observado no período |

Severidade descreve o **efeito observado**, não o esforço de correção. Um ajuste de uma
linha em `standalone.conf` pode ser crítico; uma reescrita de procedure pode ser média.
