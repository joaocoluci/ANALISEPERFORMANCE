# Fontes do pacote de log do Sankhya

O pacote `server.log_AAAAMMDDHHMMSS.zip` é gerado pela coleta de logs do Sankhya e reúne
bem mais do que o `server.log`. Cada fonte responde a uma pergunta diferente; usar só o
`server.log` deixa banco, pool e contenção de thread fora do diagnóstico.

Um pacote de porte médio tem ~700 arquivos e ~2,5 GB descompactados. **Nunca extrair**:
o coletor lê tudo por streaming direto do zip.

## Comentário do zip — o cabeçalho do ambiente

O bloco `Empresa: … Argumentos da VM: …` **não é um arquivo**: é o comentário do arquivo
zip (`ZipFile.comment`). `unzip -l` o imprime antes da listagem, o que faz parecer arquivo.
É a fonte mais densa do pacote e traz, em um lugar só:

| Campo | Uso no diagnóstico |
|---|---|
| `Empresa` | identificação do cliente no documento |
| `Versao do SankhyaW` | versão do produto |
| `Sistema Operacional` | Windows/Linux, arquitetura |
| `Memoria Heap: 4257.49 / 4995.37 MB` | **uso da heap no instante da coleta** — comparar com o Xmx |
| `Argumentos da VM` | lista completa de `-X` e `-D`; base da seção de configuração |
| `Java`, `JVM` | versão e bits |
| `Cod.Arquivo (encoding)` | confirma o encoding do log (`Cp1252`) |
| `Dir. servidor aplicações`, `Versão do servidor de aplicações` | caminho e versão do WildFly |

O valor de heap é uma amostra única, do momento da coleta — não é a média do dia.
Dizer "a heap vive a 92%" a partir dele é extrapolar; o correto é "no momento da coleta,
a heap estava a 92%".

## Logs de aplicação

Dois formatos de cabeçalho no mesmo pacote. Confundi-los é o erro mais comum.

### `server.log`, `server.log.AAAA-MM-DD` — cabeçalho COM data

```
2026-09-01 00:00:00,524 INFO  [stdout] (sw.module.jobs.scheduler_Worker-8) [Requisições][Ajuste de Ponto] Iniciado
```

```
^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2}):(\d{2}),(\d{3}) +([A-Z]+) +(?:\[([^\]]*)\] *)?(?:\(([^)]*)\) *)?(.*)$
```

Grupos: data, hora, minuto, segundo, milissegundo, nível, logger, thread, mensagem.

### `sankhya_w_*-stdout.AAAA-MM-DD.log` — cabeçalho SEM data

Este é o arquivo grande (pode passar de 2 GB). Vem do procrun do Windows e **cada linha
traz só a hora**:

```
11:35:52,352 INFO  [org.jboss.modules] (main) JBoss Modules version 1.6.1.Final
```

A data inicial vem do **nome do arquivo** (`…-stdout.2026-06-01.log`) e o arquivo cobre
meses de operação. Reconstrução da data: sempre que a hora **retrocede** em relação à
linha anterior, virou o dia — soma-se um dia ao contador. Sem essa lógica, todo evento do
arquivo cai no mesmo dia e a série temporal por hora fica inútil.

O `stdout` concentra o volume real de exceções: em um pacote observado, o `server.log`
tinha 7.649 ERROR e o `stdout` passava de 230 mil ocorrências de `Exception`.

### Linhas de continuação

Stacktrace, SQL quebrado e `Caused by:` vêm **sem cabeçalho**. Herdam nível, thread e
timestamp da última linha com cabeçalho. Num pacote observado, 159 mil das 187 mil linhas
do `server.log` eram continuação — contar linha em vez de entrada infla qualquer número.

### `sankhya_w_*-stderr.*.log`, `service.AAAA-MM-DD.log`

Pequenos, quase sempre só o registro de início/parada do serviço Windows. Úteis para
detectar **reinícios não planejados**, que explicam janelas sem log.

## `dml_stats/SANKHYA_dmlstats_DD-MM-AAAA.log`

Gerado pelo `extratorDML.jar` da Sankhya. CSV **sem cabeçalho**, seis colunas:

```
OBJETO , TS_HORA_MS , OP , EXECUCOES , TEMPO_TOTAL_MS , LINHAS
TGFCAB , 1788231600000 , 0 , 12 , 4596 , 12
```

| Coluna | Conteúdo |
|---|---|
| `OBJETO` | tabela ou procedure |
| `TS_HORA_MS` | epoch em ms, truncado na **hora** — é um bucket horário, não o instante do comando |
| `OP` | `0`=INSERT · `1`=UPDATE · `2`=DELETE · `3`=STP (procedure) |
| `EXECUCOES` | comandos no bucket |
| `TEMPO_TOTAL_MS` | soma do tempo, em ms |
| `LINHAS` | linhas afetadas |

O mapeamento de `OP` foi confirmado por três vias: `STP_*` só aparece com `3`; `TSILOGID`
(tabela de log, só recebe inserção) só aparece com `0`; `TGFNUM` (controle de numeração,
só recebe atualização) só aparece com `1`. E a média calculada de `STP_SET_SESSION2` bate
com o limite oficial de 10 ms do checklist.

**Tempo médio = `TEMPO_TOTAL_MS / EXECUCOES`.** É esse número que se compara com os
limiares do checklist (`catalogo-gargalos.md`).

Medidas negativas aparecem raramente (1 linha em 3 milhões num pacote observado) e são
corrupção do extrator, não tempo real. Descartar e informar a quantidade descartada —
somar `2^32` produziria um objeto com bilhões de milissegundos e um achado falso.

## `conn-stats/connection_stats_DDMMAAAA.dat`

Binário, big-endian, registro fixo de **20 bytes**, uma amostra a cada **5 minutos**
(288 por dia, arquivo de 5.760 bytes):

```
struct: >q i i i     →  timestamp_ms, A, B, C
```

`A` é a série de conexões publicada pelo sistema. `B` e `C` vieram zerados em todos os
pacotes examinados; ficam registrados sem rótulo até haver confirmação de significado.
**Não inventar rótulo para eles no documento.**

Cruzar o pico de `A` com `max-pool-size` do `mge-ds.xml`: pool no teto faz a requisição
esperar por conexão livre, o que o usuário sente como lentidão geral e o log não registra
como erro.

## `threads.dump`

Snapshot único, formato próprio do Sankhya (não é o `jstack` padrão):

```
Dump das 331 thread gerado em 2026/09/01 23:39:05 BRT

"OracleTimeoutPollingThread" prio=10 tid=417 TIMED_WAITING deamon
    native=false, suspended=false, block=0, wait=1714844
    lock=null owned by null (-1), cpu=703, user=203
        java.lang.Thread.sleep(Native Method)
        …
```

Cabeçalho: nome, prioridade, tid, **estado**, tipo (`deamon`/`worker`). Segunda linha:
`block` e `wait` (contadores acumulados). Terceira: lock, dono do lock, `cpu` e `user`
em ms. Depois, a pilha.

O que interessa: threads em `BLOCKED` e quem detém o lock; `cpu` alto concentrado em
poucas threads; e o agrupamento por prefixo de nome (`default task-N`, `sw.module.jobs.*`)
para dimensionar pools.

**Um dump é uma foto.** Ele mostra o estado de um instante — não prova que a contenção é
permanente. Usar como corroboração de um sinal visto no log, nunca como prova isolada.

## `.ald/cb-AAAA-MM-DD.log`

Trilha de acesso (Control Board). Um arquivo por dia, com blocos assim:

```
07:23:45,829 CBL INFO:
User: 61 -> NATALIA DA, SK_ID:353429
|URL: http://host:8180/mge/service.sbr serviceName=WorkspaceSP.openItemMenu&counter=3
|IP: 201.75.209.249 (201.75.209.249)
|User-Agent: …
[CB-ACM] CODUSU: 61 SEQACESSO: 1268592206 DHACESSO: 2026-09-01 07:23:45.828 RESOURCEID: br.com.sankhya.tim.cad.contratovendalote CAMINHO: Imobiliária » Cadastros » Contratos DESCRMENU: Contrato de Venda de Lote
```

Rende o perfil de carga: telas mais abertas, usuários mais ativos, serviços mais chamados,
distribuição por hora e sessões distintas por dia. É o que permite dizer se a lentidão é
**generalizada** ou **localizada** — a distinção que organiza todo o checklist do Service Desk.

Contém nome de usuário e IP. Ver a regra de dados pessoais no `SKILL.md`.

## `parametros.properties`

Parâmetros do sistema. Interessam ao diagnóstico: `SERVERHOSTSCHED` (onde os JOBs rodam),
`QTDENVIOMSGJOB`, `MSDINTAGENDADOR`, e os de sessão. Arquivo grande — não despejar inteiro
no documento.

## `version.properties`

Versão de cada módulo (`mge`, `mgefin`, `mgeprod`, …). Vai na seção de ambiente e serve
para checar defasagem entre módulos.

## `mge-ds.xml`

Datasource: driver, `min-pool-size`, `max-pool-size`, `prefill`. O `max-pool-size` é o
denominador do cálculo de saturação do pool. **A URL pode conter host, porta e SID —
nunca reproduzir credencial no documento.**

## `sas-server/<id>/serverAAAAMMDD-HHMM.log`

Log do SAS (licenciamento). Lista os módulos licenciados e a quantidade de cada um.
Serve para confrontar concorrência licenciada com sessões observadas no `.ald`.

## `bootloader/`, `listeners-externos.txt`, `audit.log`

`bootloader/` são centenas de arquivos pequenos de carga de módulo — ruído para performance.
`listeners-externos.txt` lista os listeners registrados, útil quando a suspeita recai sobre
personalização. `audit.log` costuma vir vazio.

## Pacote do Monitor de Consultas — segundo pacote, arquivo separado

O cliente entrega **dois** pacotes quando o Monitor de Consultas esteve ligado. O segundo
tem nome dado pelo navegador (`Monitoramento (15).zip`, `Monitoramento.zip`) e dois
arquivos dentro:

| Arquivo | Conteúdo |
|---|---|
| `Monitor_Consulta.log` | tempo, `Runtime-info` quando há, o SQL e a lista `Params:` |
| `Monitor_Processos.log` | a pilha Java que originou o **mesmo** bloco |

Os dois se casam pelo identificador de bloco. Blocos separados por uma linha de tracejado:

```
-------------------------------------------------------------------------------------
##ID_8627## tempo: 4 (ms)
/* Runtime-info
Application: ImportadorDados
Referer: https://cliente.exemplo.com.br/mgebase/ImportadorDados.xhtml5
ResourceID: br.com.sankhya.importadorDados
service-name: ImportadorDadosSP.validaNomeArquivo
uri: /mgebase/service.sbr
*/
SELECT T.ULTCOD, T.SERIE FROM TGFNUM T WHERE T.ARQUIVO = ? AND T.CODEMP = ? FOR UPDATE
Params:
  1 = TSILIL
```

E no outro arquivo, o mesmo `##ID_8627##` seguido da pilha, de `JDBCSpy` até o servlet.

### Por que os dois arquivos importam

`Runtime-info` **só aparece em uma fração dos blocos**. Num pacote medido, 553 de 16.013;
os outros 15.460 só têm origem porque a pilha do segundo arquivo responde quem chamou.
Analisar apenas o `Monitor_Consulta.log` deixa 96% das consultas sem dono.

Da pilha o coletor tira quatro coisas, e só elas — guardar a pilha inteira de centenas de
milhares de blocos não caberia em memória e não serviria:

- **primeiro frame que não é infraestrutura** — quem chamou. `JDBCSpy`, `jape`, `undertow`,
  `servlet`, proxy dinâmico, `tinyejb` e o motor de script ficam de fora: aparecem em toda
  pilha e não dizem nada a quem vai corrigir;
- **`bsh.`** na pilha — a consulta nasceu em evento programável / regra escrita fora do
  produto, ainda que o frame de negócio abaixo dele seja do produto;
- **pacote fora de `br.com.sankhya`** (`simulacaopreco.…`) — módulo Java personalizado;
- **`SendErrorPageHandler`, `MGEModelException`** — a requisição terminou em erro. Isso
  **não** diz que a consulta falhou: ela pode ter executado bem e a requisição ter
  falhado depois.

`BackgroundProcess` na pilha é execução fora de requisição de usuário. `BackgroundProcessSP`
**não** é: é o serviço que a tela chama para perguntar o andamento do processo, e roda
dentro da requisição. Sem essa distinção, toda tela que acompanha uma importação entra no
relatório como processo em segundo plano.

### O que este pacote não tem

- **Não tem data nem hora.** Nenhum bloco carrega timestamp; o `##ID_n##` é sequencial,
  não é relógio. Logo **não se cruza a janela do monitor com a do `server.log` pelo dado**:
  a sobreposição das duas janelas tem de ser perguntada a quem coletou, e o documento diz
  o que foi confirmado.
- **Não tem contagem de linhas retornadas** nem plano de execução. Consulta rápida que
  devolve 200 mil linhas aparece aqui como rápida.
- A captura cobre **o intervalo em que o monitor ficou ligado**, que costuma ser curto. Um
  pacote pode não conter a rotina lenta de que o cliente reclama — e aí o resultado benigno
  do monitor não desmente o `server.log`; só não fala sobre ele.

### `Params:` — dado do cliente

A lista de parâmetros traz valor de negócio: documento, valor de título, nome de pessoa.
O coletor guarda **a quantidade de parâmetros, nunca o valor**, e o teste de regressão
falha se algum valor vazar para o JSON. No documento não entra parâmetro em nenhuma
hipótese, nem em bloco de evidência.

## Fonte que o pacote **não** traz

Estas respondem perguntas que o pacote deixa em aberto. Quando o diagnóstico depender
delas, a seção de limitações do documento tem de dizer isso:

- **Log de GC** (`-Xloggc:`) — pausa real do coletor. Sem ele, a análise de GC é indireta.
- **AWR/Statspack ou `sp_WhoIsActive`** — plano de execução e espera no banco. É o que
  falta para transformar "consulta ofensiva" em causa.
- **Métricas de SO** — CPU, memória, IO e rede do servidor ao longo do tempo.
- **Monitor de Consultas, quando o cliente não o ligou.** Sem ele, consulta lenta
  individual com o SQL não é observável; `dml_stats` só agrega por objeto.
