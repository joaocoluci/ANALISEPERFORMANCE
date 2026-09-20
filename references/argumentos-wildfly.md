# Argumentos da VM — WildFly Sankhya

Os "Argumentos da VM" registrados no cabeçalho do pacote são a fonte da seção de
configuração do documento. Este arquivo diz o que cada argumento faz e quando a ausência
ou o valor merece virar recomendação.

Fontes: artigo *Configuração de argumentos para Wildfly* da central de ajuda Sankhya, guia
interno de argumentos, e o `standalone.conf` do pacote de referência
(`baseline-wildfly23.md`).

## Erro no log e o argumento correspondente

O artigo oficial liga alguns argumentos diretamente ao erro que eles tratam. É o atalho mais
direto entre o que o log mostra e o que se recomenda:

| Erro no log | Argumento | Observação |
|---|---|---|
| `ORA-01013` | `-Djape.global.query.timeout` (segundos) | aumentar só depois de olhar a consulta: o timeout existe para conter consulta ruim, e elevá-lo esconde a causa |
| `JapeSession timeout` / `JapeSessionInterruptedError` | `-Djape.session.timeout` (milissegundos) | rotina que faz milhares de consultas rápidas estoura aqui, não no timeout de query |
| `WFLYCTL0348` no deploy | `-Djboss.as.management.blocking.timeout` | o padrão do WildFly é 300 s |
| `[LoginUnico] Informações incompletas` | `-Dlogin.unico.ativo=false` | ignora a checagem de login único |
| `SELECT FROM DUAL` em volume | `-Djape.check.is.valid.connection=false` | desliga a validação de conexão; ver o efeito colateral na tabela de JAPE |

Aumentar um timeout é a recomendação de menor esforço e a de maior chance de estar errada.
Ela trata o sintoma. Só entra no documento junto da investigação da consulta ou da rotina,
nunca sozinha.

Alterações vão em `standalone.conf` (Linux) ou `standalone.conf.bat` (Windows), em
`wildfly_producao/bin/`. **Toda alteração exige reinício do servidor** — dizer isso na
recomendação, porque muda a janela de aplicação.

Ao acrescentar argumento, criar linha nova iniciando com `JAVA_OPTS`, em vez de editar a
linha existente.

## Memória e coletor de lixo

| Argumento | Efeito | Quando recomendar |
|---|---|---|
| `-Xms` / `-Xmx` | heap inicial e máxima | **sempre iguais**; mínimo 1024 MB |
| `-XX:MaxMetaspaceSize=` | limita metaspace | ambiente com muitos módulos e redeploys |
| `-XX:+UseG1GC` | coletor G1, baixa latência | heap grande; substitui CMS |
| `-XX:MaxGCPauseMillis=` | pausa alvo do G1 | junto com G1 |
| `-XX:InitiatingHeapOccupancyPercent=30` | ocupação que dispara o ciclo | junto com G1 |
| `-XX:G1ReservePercent=10-20` | folga contra Full GC | junto com G1 |
| `-XX:+ParallelRefProcEnabled` | processamento paralelo de referências | junto com G1 |
| `-XX:+UseStringDeduplication` | deduplica strings | heap grande com muita string |
| `-XX:+AlwaysPreTouch` | pré-aloca a heap | reduz page fault; sobe mais devagar |
| `-XX:MaxDirectMemorySize=` | limita memória direta (NIO/Netty) | consumo fora da heap |

`-XX:+UseConcMarkSweepGC` (CMS) foi descontinuado a partir do Java 9 e fragmenta em heap
grande. Presente, vira recomendação de avaliação — **nunca de troca imediata**: mudar
coletor altera o perfil de pausa e precisa de janela de validação.

## Diagnóstico e log de GC

| Argumento | Efeito |
|---|---|
| `-XX:+PrintGCDetails -XX:+PrintGCDateStamps -XX:+PrintTenuringDistribution` | detalhe do GC |
| `-XX:+PrintGCApplicationStoppedTime` | tempo de pausa visível para a aplicação |
| `-Xloggc:/caminho/gc.log` | arquivo de log de GC |
| `-XX:+UseGCLogFileRotation -XX:NumberOfGCLogFiles=5 -XX:GCLogFileSize=20M` | rotação |
| `-XX:+HeapDumpOnOutOfMemoryError` | dump em estouro de memória |
| `-XX:HeapDumpPath=` | destino do dump — precisa existir e ter espaço |
| `-XX:ErrorFile=` | log de erro fatal da JVM |
| `-XX:+ExitOnOutOfMemoryError` | encerra o processo no estouro |
| `-XX:-OmitStackTraceInFastThrow` | mantém stacktrace em exceção repetida |

**Ausência de `-Xloggc:` é a maior limitação de uma análise de memória.** Sem ele, não há
como medir pausa de coleta — só inferir. Quando a hipótese for GC, recomendar ligar o log
e recoletar, e dizer isso na seção de limitações.

`-XX:+HeapDumpOnOutOfMemoryError` ausente merece recomendação sempre: sem o dump, o próximo
estouro não deixa evidência.

## Sistema e locale

| Argumento | Efeito |
|---|---|
| `-Djava.net.preferIPv4Stack=true` | força IPv4 |
| `-Dsun.net.inetaddr.ttl=60` | TTL do cache de DNS |
| `-Dfile.encoding=` | codificação padrão (`ISO8859-1` no padrão Sankhya) |
| `-Duser.language=pt -Duser.country=BR` | locale |
| `-Duser.timezone=America/Sao_Paulo` | fuso |
| `-Djava.awt.headless=true` | modo headless |
| `-Djava.security.egd=file:/dev/urandom` | entropia rápida — evita travar na subida em Linux |
| `-Djava.io.tmpdir=` | diretório temporário |

## WildFly

| Argumento | Efeito |
|---|---|
| `-Djboss.socket.binding.port-offset=` | soma a 8080; offset 100 → porta 8180 |
| `-Djboss.bind.address=0.0.0.0` | bind público |
| `-Djboss.bind.address.management=0.0.0.0` | necessário para JConsole e VisualVM |
| `-Djboss.as.management.blocking.timeout=3600` | timeout de management; trata `WFLYCTL0348` no deploy |
| `-Djboss.server.log.dir=` | pasta de log |
| `-Dorg.jboss.as.logging.per-deployment=false` | log único, não por deploy |
| `-Djboss.node.name=` | nome do nó |

## Transações

| Argumento | Efeito |
|---|---|
| `-Dcom.arjuna.ats.arjuna.allowMultipleLastResources=true` | permite múltiplos last-resource |
| `-Dcom.arjuna.ats.coordinator.afterCompletion.reverse.order=false` | ordem dos callbacks |

## JAPE — específicos Sankhya

Os que interessam ao diagnóstico:

| Argumento | Efeito | Leitura |
|---|---|---|
| `-Djape.global.query.timeout` | timeout de consulta, **em segundos** | valor alto esconde consulta ruim; baixo derruba rotina legítima |
| `-Djape.session.timeout` | timeout de sessão, **em milissegundos** | 1800000 = 30 min |
| `-Djape.experimental.commit-type=B` | tipo de commit | recomendado pelo checklist |
| `-Djape.experimental.always.reuse.jdbc.conn=true` | reuso agressivo de conexão | reduz pressão no pool |
| `-Djape.experimental.lock.strategy=1` | estratégia diferencial de lock | — |
| `-Djape.lazy.init=true` | não carrega metadados na subida | recomendado quando a inicialização é lenta |
| `-Djape.lob.fields.as.lazy=true` | LOB sob demanda | reduz tráfego e memória |
| `-Djape.jdbc.monitor.enabled=true` | monitor de JDBC ativo | necessário para as estatísticas |
| `-Djape.jdbc.monitor.timeout.tolerance` | tolerância extra ao timeout | — |
| `-Djape.jdbc.check.select=true` | valida o SELECT de relatórios e dashboards | — |
| `-Djape.check.is.valid.connection=false` | desliga o `SELECT FROM DUAL` de validação | ganha desempenho, **perde a proteção contra conexão morta** — relacionar com `ORA-17008` no log |
| `-Djape.use.write.history=false` | desliga histórico de escrita | reduz IO |
| `-Djape.use.connection.recorder=false` | desliga gravador de conexões | reduz IO |

## Numeração e chaves

| Argumento | Efeito |
|---|---|
| `-Dskw.use.procedure.tgfnum=true` | numeração por procedure |
| `-Dskw.use.procedure.tgfnum.rule=TGFCAB,TGFFIN,…` | tabelas que usam a procedure |
| `-Dskw.use.procedure.tgfnum.numnota=false` | desabilita `STP_NUMERAR_NOTA2` |
| `-Dskw.uid-gen.strategy=` | estratégia de geração de identificadores |

Relacionar com `dml_stats`: `STP_KEYGEN_TGFNUM` e `TGFNUM` com tempo alto apontam para
contenção na numeração.

## Jobs

| Argumento | Efeito | Risco |
|---|---|---|
| `-Dsankhyaw.schedule.disable=true` | **nenhum job executa** | silencioso; rotina simplesmente não roda |
| `-Dsankhyaw.only.jobs=-22005,-22010` | só os jobs listados executam | silencioso; o resto não roda |
| `-Dskw.cluster.nodes=IP1,IP2` | nós do cluster | — |
| `-Dskw.cluster.pref.run.job=true` | nó executor de jobs | — |

Complementa o parâmetro `SERVERHOSTSCHED` (vazio = local; IP = todos naquele servidor;
`IP:NomeDoJob` = só os listados).

Os dois primeiros aparecem em ambiente de produção por herança de configuração de teste.
Quando presentes, verificar se é intencional antes de tratar como problema — em nó de
cluster sem jobs, é o correto.

## Autorização e sessão

| Argumento | Efeito |
|---|---|
| `-Dsnk.use.action.auth=true` | autorização por ação |
| `-Dsnk.authorization.layer.enable=true` | camada de autorização da API |
| `-Dsnk.sessioncycle.debug.enable=true` | log de criação e encerramento de sessão |
| `-Dlogin.unico.ativo=false` | ignora checagem de login único |

`snk.sessioncycle.debug.enable` gera volume alto de log. Presente em produção sem
investigação ativa, vale recomendar desligar.

## IO

| Argumento | Efeito |
|---|---|
| `-Depoll.hang.log` / `-Depoll.hang.timeout=180000` | detecção de trava de epoll |
| `-Dxnio.nio.selector.*=sun.nio.ch.PollSelectorProvider` | força Poll em vez de Epoll |

Sinal `epoll_hang` no log com `epoll.hang.log=false` significa que a detecção está ligada
mas o log detalhado, não. Recomendar ligar quando o sinal aparecer.
