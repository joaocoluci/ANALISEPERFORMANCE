#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste de regressao dos detectores do coletor.

Roda em segundos, sem precisar de pacote de log. Executar sempre que mexer em
SINAIS, P_GATILHO, EXCLUSOES_SINAL ou nos padroes de driver e banco.

  python testar_sinais.py

Existe porque tres defeitos ja passaram por aqui e chegaram perto do documento
do cliente:
  - "Deadlock relatado" que era o nome da classe StripedLockDeadlockScanner;
  - "Trava de epoll" que era o argumento -Depoll.hang.log na linha de boot;
  - contagem de reinicios inflada por um padrao colado no sinal errado.

Todos seriam pegos por este arquivo em dois segundos.
"""

import json
import sys
import os
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coletar_metricas as C  # noqa: E402
import coletar_monitor as M  # noqa: E402


# Linha de log real (ou fiel a uma real) -> rotulos que ela DEVE produzir.
CASOS_POSITIVOS = [
    (b'11:35:53,509 INFO  [org.jboss.as] (MSC service thread 1-1) WFLYSRV0049: '
     b'WildFly Full 11.0.0.Final (WildFly Core 3.0.8.Final) starting',
     {"servidor_subindo"}),
    (b'java.lang.OutOfMemoryError: Java heap space', {"oom_heap"}),
    (b'java.lang.OutOfMemoryError: GC overhead limit exceeded', {"gc_overhead"}),
    (b'java.lang.OutOfMemoryError: Metaspace', {"oom_outro"}),
    (b'java.net.SocketTimeoutException: Read timed out', {"timeout_socket"}),
    (b'Caused by: java.lang.IllegalStateException: A pagina de dados 2foi gerada, '
     b'mas demorou muito a ser consumida', {"datapager_lento"}),
    (b'Caused by: javax.resource.ResourceException: IJ000453: Unable to get '
     b'managed connection for java:/MGEDS', {"pool_exausto"}),
    (b'ORA-00060: deadlock detected while waiting for resource', {"deadlock_java"}),
    (b'Caused by: java.sql.SQLTimeoutException: ORA-01013: o usuario solicitou o '
     b'cancelamento da operacao atual', {"timeout_query"}),
    (b'java.sql.SQLRecoverableException: Closed Connection', {"conexao_fechada"}),
    (b'UT005023: Exception handling request to /mge/service.sbr', {"erro_undertow"}),
    (b'WFLYCTL0348: Timeout after [300] seconds waiting for service container stability',
     {"deploy_timeout"}),
    (b'[Full GC (Ergonomics) 4000M->3800M(5012M), 2.5 secs]', {"full_gc"}),
    (b'WARN [org.xnio] epoll thread hang detected after 180000ms', {"epoll_hang"}),
    (b'at org.jboss.jca.core.connectionmanager.pool.mcp.Semaphore'
     b'ConcurrentLinkedDequeManagedConnectionPool.validateConnections(:1443)',
     {"pool_validacao"}),
    (b'ARJUNA016102: TransactionReaper::check timed out for TX '
     b'0:ffff0a000001:1a2b:5f0e:12 in state RUN', {"timeout_txn"}),
    (b'java.sql.SQLException: ORA-02396: excedeu o tempo maximo de inatividade',
     {"sessao_expirada"}),
]

# Linhas que casam algum literal mas NAO sao o evento. Devem produzir nada.
CASOS_NEGATIVOS = [
    ("scanner de deadlock",
     b'WARN [com.sankhya.util.ResourceLock] (StripedLockDeadlockScanner task) '
     b'Excecao no scan de deadlock (continuando): java.lang.InterruptedException'),
    ("argumento epoll na linha de boot",
     b'  JAVA_OPTS: "-Xms2048m -Xmx5012m -Depoll.hang.log=false '
     b'-Depoll.hang.timeout=180000 -Djape.global.query.timeout=600"'),
    # Os tres casos abaixo sao linhas REAIS de um pacote de cliente. Elas
    # produziram "estouro de memoria: 2 ocorrencias" e "trava de epoll: 4
    # ocorrencias" num relatorio, e as duas eram falsas. O que casou foi o NOME
    # do argumento, nunca um evento.
    ("dump de argumentos da VM pelo logger de configuracao",
     b'2026-08-25 12:08:12,058 DEBUG [org.jboss.as.config] (MSC service thread 1-2) '
     b'VM Arguments: -D[Standalone] -Xms4096m -Xmx4096m -XX:+UseG1GC '
     b'-Depoll.hang.log=false -Depoll.hang.timeout=180000 '
     b'-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/home/mgeweb/dump'),
    ("eco de configuracao do standalone.conf, chave epoll",
     b'\tepoll.hang.log = false'),
    ("eco de configuracao do standalone.conf, timeout de epoll",
     b'\tepoll.hang.timeout = 180000'),
    ("eco de configuracao com nome de argumento de memoria",
     b'\tjava.opts = -XX:+ExitOnOutOfMemoryError'),
]


def rotulos(linha):
    """Reproduz exatamente a contagem do coletor para uma linha."""
    if not C.P_GATILHO.search(linha) or C.P_LINHA_CONFIG.search(linha):
        return set()
    achados = set()
    m = C.P_SINAIS.search(linha)
    while m:
        rot = m.lastgroup
        excl = C.EXCLUSOES_SINAL.get(rot)
        if not (excl and any(x in linha for x in excl)):
            achados.add(rot)
        m = C.P_SINAIS.search(linha, m.end())
    return achados


# ------------------------------------------------- Monitor de Consultas
# Pacote sintetico: dois arquivos que se casam pelo ##ID_n##, como o real.
# Exercita agrupamento por impressao do SQL, deteccao de comando e objeto,
# pontos de atencao, marcador de erro, exclusao do BackgroundProcessSP e o
# sigilo dos valores de parametro.
SEP = "-" * 103

MONITOR_CONSULTA = "\n".join([
    SEP,
    "##ID_1## tempo: 12",
    "/* Runtime-info",
    "Application: workspace",
    "service-name: CACSP.confirmarNota",
    "uri: /mge/service.sbr",
    "*/",
    "SELECT NUNOTA FROM TGFCAB WHERE CODPARC = 4321 AND DTNEG > '01/01/2026'",
    "Params:",
    "  1 = 4321",
    SEP,
    # mesma consulta, outro literal: tem de cair na MESMA impressao
    "##ID_2## tempo: 8",
    "SELECT NUNOTA FROM TGFCAB WHERE CODPARC = 9999 AND DTNEG > '05/02/2026'",
    SEP,
    # lenta, sem filtro, projecao com asterisco, objeto personalizado
    "##ID_3## tempo: 7400",
    "SELECT * FROM AD_MOVIMENTOAUX",
    SEP,
    # funcao aplicada a coluna do filtro
    "##ID_4## tempo: 2500",
    "UPDATE TGFITE SET QTDNEG = 1 WHERE TRUNC(DTALTER) = TRUNC(SYSDATE)",
    SEP,
    # consulta que falhou: marcador de erro no proprio bloco
    "##ID_5## tempo: 3",
    "SELECT CODPROD FROM TGFPRO WHERE CODPROD = 7",
    'java.sql.SQLSyntaxErrorException: ORA-00904: "CODPRODX": identificador invalido',
    SEP,
    # procedure personalizada, com valor sensivel no parametro
    "##ID_6## tempo: 4",
    "{call STP_AD_RECALCULA(?, ?)}",
    "Params:",
    "  1 = 12345678901",
    "  2 = Fulano de Tal",
    "",
])

MONITOR_PROCESSOS = "\n".join([
    SEP,
    "##ID_1##",
    "deployment.sankhyaw.ear.lib.jape-4.jar//br.com.sankhya.jape.dao.JDBCSpy.logSql(JDBCSpy.java:87)",
    "deployment.sankhyaw.ear.ejb.mge-modelcore-4.jar//br.com.sankhya.modelcore.facades.CACSPBean.confirmar(CACSPBean.java:120)",
    "io.undertow.servlet@2.2.5.Final//io.undertow.servlet.handlers.ServletHandler.handleRequest(ServletHandler.java:74)",
    SEP,
    "##ID_2##",
    # servico que a TELA chama para acompanhar processo: NAO e background
    "deployment.sankhyaw.ear.ejb.mge-modelcore-4.jar//br.com.sankhya.modelcore.facades.BackgroundProcessSPBean.getHistoryOfProcess(BackgroundProcessSPBean.java:88)",
    SEP,
    "##ID_3##",
    # execucao realmente em background, e originada de script
    "deployment.sankhyaw.ear.lib.bsh.jar//bsh.Reflect.invokeOnMethod(Reflect.java:1)",
    "deployment.sankhyaw.ear.ejb.mge-modelcore-4.jar//br.com.sankhya.modelcore.util.BackgroundProcess.lambda$addProcess$163(BackgroundProcess.java:1)",
    SEP,
    "##ID_4##",
    # modulo personalizado: pacote que nao e do produto
    "simulacaopreco.EventoItemImportacaoSimulacaoPreco.atualizaSimulacao(Evento.java:44)",
    SEP,
    "##ID_5##",
    "deployment.sankhyaw.ear.ejb.mge-modelcore-4.jar//br.com.sankhya.modelcore.MGEModelException.throwMe(MGEModelException.java:1)",
    "io.undertow.servlet@2.2.5.Final//io.undertow.servlet.handlers.SendErrorPageHandler.handleRequest(SendErrorPageHandler.java:52)",
    SEP,
    "##ID_6##",
    "deployment.sankhyaw.ear.ejb.mge-modelcore-4.jar//br.com.sankhya.modelcore.facades.PersonalizacaoSPBean.roda(Personalizacao.java:9)",
    "",
])


def _pacote_sintetico(pasta):
    for nome, conteudo in (("Monitor_Consulta.log", MONITOR_CONSULTA),
                           ("Monitor_Processos.log", MONITOR_PROCESSOS)):
        with open(os.path.join(pasta, nome), "w", encoding=M.ENC,
                  errors="replace") as f:
            f.write(conteudo)


def _agregado(execucoes, tempo_ms, maximo):
    a = M.Agregado("SELECT 1", "SELECT", [], [])
    a.execucoes = execucoes
    a.tempo_ms = tempo_ms
    a.maximo_ms = maximo
    return a


def testar_monitor():
    """Roda o coletor do monitor num pacote sintetico e confere o resultado."""
    falhas = []
    pasta = tempfile.mkdtemp(prefix="monitor_teste_")
    try:
        _pacote_sintetico(pasta)
        mon = M.bloco_monitor(pasta)
        if mon.get("erro"):
            return [f"monitor: bloco_monitor recusou o pacote sintetico: {mon['erro']}"]

        def falhar(msg):
            falhas.append("monitor: " + msg)

        if mon["consultas_capturadas"] != 6:
            falhar(f"esperava 6 execucoes, obtive {mon['consultas_capturadas']}")
        # ID_1 e ID_2 sao a mesma consulta com literais diferentes
        if mon["consultas_distintas"] != 5:
            falhar(f"esperava 5 consultas distintas (ID_1 e ID_2 juntos), "
                   f"obtive {mon['consultas_distintas']}")

        por_objeto = {}
        for x in mon["ofensivas"]:
            for o in x["objetos"]:
                por_objeto.setdefault(o, x)

        cab = por_objeto.get("TGFCAB")
        if not cab or cab["execucoes"] != 2:
            falhar("TGFCAB deveria somar 2 execucoes na mesma impressao")
        if cab and cab["origens"][0]["origem"] != "CACSP.confirmarNota":
            falhar(f"origem por Runtime-info perdida: {cab and cab['origens']}")

        aux = por_objeto.get("AD_MOVIMENTOAUX")
        if not aux:
            falhar("consulta sobre AD_MOVIMENTOAUX nao entrou no ranking")
        else:
            for rot in ("sem_filtro", "select_estrela", "objeto_personalizado",
                        "origem_em_script"):
                if rot not in aux["atencao"]:
                    falhar(f"AD_MOVIMENTOAUX sem o ponto {rot}: {aux['atencao']}")
            if aux["classe"] not in ("critica", "alta"):
                falhar(f"7,4 s deveria pontuar alta ou critica, deu "
                       f"{aux['pontuacao']} ({aux['classe']})")

        ite = por_objeto.get("TGFITE")
        if ite and "funcao_no_filtro" not in ite["atencao"]:
            falhar(f"TRUNC na coluna do filtro nao detectado: {ite['atencao']}")
        if ite and "origem_personalizada" not in ite["atencao"]:
            falhar("pacote fora do produto deveria marcar origem personalizada")

        # BackgroundProcessSP e requisicao de usuario, nao execucao em background
        if cab and "execucao_em_background" in cab["atencao"]:
            falhar("BackgroundProcessSP marcado como execucao em background")
        if not any(c["rotulo"] == "execucao_em_background"
                   for c in mon.get("contexto", [])):
            falhar("execucao em background nao chegou ao bloco de contexto")
        if any(a["rotulo"] in M.ATENCAO_CONTEXTO for a in mon["atencao"]):
            falhar("rotulo de contexto vazou para a lista de pontos de atencao")

        if mon["sem_marcador_de_erro"]:
            falhar("ORA-00904 no bloco nao foi reconhecido como erro")
        elif mon["erros"][0]["marcador"] != "ORA-00904":
            falhar(f"marcador de erro errado: {mon['erros'][0]['marcador']}")
        if not mon["requisicoes_com_erro"]:
            falhar("pilha com SendErrorPageHandler nao contou requisicao com erro")

        # Valor de parametro nunca entra no resultado.
        despejo = json.dumps(mon, ensure_ascii=False)
        for sigiloso in ("12345678901", "Fulano de Tal"):
            if sigiloso in despejo:
                falhar(f"valor de parametro vazou para o JSON: {sigiloso!r}")

        # A pontuacao tem de crescer com o tempo medio, mantido o resto.
        p_lenta = M.pontuar(_agregado(10, 100000, 12000), 1000000, 11000)[0]
        p_rapida = M.pontuar(_agregado(10, 100, 20), 1000000, 15)[0]
        if not p_lenta > p_rapida:
            falhar(f"pontuacao nao cresce com o tempo medio ({p_lenta} vs {p_rapida})")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    return falhas


def testar_banco():
    """Regressao da deteccao de dialeto e do catalogo de scripts.

    O caso que justifica este bloco: um ambiente Oracle com o driver de SQL
    Server tambem carregado no deploy. Decidindo pela lista de drivers, o
    documento entrega ao cliente cinco scripts do banco errado.
    """
    falhas = []

    def falhar(msg):
        falhas.append("banco: " + msg)

    def ev(url=None, driver=None, banner=None, carregados=()):
        return {
            "ambiente": {"datasource": {k: v for k, v in
                                        (("url", url), ("driver", driver)) if v}},
            "logs": {
                "banco": [{"banner": banner, "ocorrencias": 1}] if banner else [],
                "drivers_carregados": [{"classe": c, "versao": "1.0"} for c in carregados],
            },
        }

    # 1. URL decide, mesmo com dois dialetos entre os drivers carregados.
    b = C.bloco_banco(ev(url="jdbc:oracle:thin:@10.0.0.1:1521/ORCL",
                         banner="Oracle Database 11g Release 11.2.0.4.0",
                         carregados=("oracle.jdbc.OracleDriver",
                                     "com.microsoft.sqlserver.jdbc.SQLServerDriver",
                                     "org.h2.Driver")))
    if b["dialeto"] != "oracle":
        falhar(f"URL Oracle nao resolveu para oracle: {b['dialeto']}")
    if b["drivers_carregados"] != ["oracle", "sqlserver"]:
        falhar(f"drivers carregados nao listados: {b['drivers_carregados']}")
    if b["fonte"] != "URL do datasource em mge-ds.xml":
        falhar(f"fonte errada com URL presente: {b['fonte']}")
    if "10.0.0.1" in (b["evidencia"] or ""):
        falhar("host do datasource vazou na evidencia")

    # 1b. O caso que separa a precedencia de verdade: URL de um dialeto e UM
    # unico driver do outro. Sem este caso, inverter a ordem de precedencia
    # passa pela regressao — os dois drivers do caso 1 nao decidem nada, e o
    # caso 7 resolve igual nas duas ordens.
    b = C.bloco_banco(ev(url="jdbc:oracle:thin:@srv:1521/ORCL",
                         carregados=("com.microsoft.sqlserver.jdbc.SQLServerDriver",)))
    if b["dialeto"] != "oracle":
        falhar(f"URL Oracle perdeu para driver unico de SQL Server: {b['dialeto']}")
    if b["fonte"] != "URL do datasource em mge-ds.xml":
        falhar(f"precedencia invertida: decidiu por '{b['fonte']}'")

    # 1c. Banner de um dialeto e driver unico do outro: o banner prevalece.
    b = C.bloco_banco(ev(banner="Oracle Database 19c Release 19.0.0.0.0",
                         carregados=("com.microsoft.sqlserver.jdbc.SQLServerDriver",)))
    if b["dialeto"] != "oracle" or b["fonte"] != "banner do banco no server.log":
        falhar(f"banner perdeu para driver unico: {b['dialeto']} por {b['fonte']}")

    # 1d. Driver do datasource de um dialeto e driver unico carregado do outro.
    b = C.bloco_banco(ev(driver="com.oracle.ojdbc",
                         carregados=("com.microsoft.sqlserver.jdbc.SQLServerDriver",)))
    if b["dialeto"] != "oracle" or b["fonte"] != "classe do driver do datasource":
        falhar(f"driver do datasource perdeu para driver carregado: "
               f"{b['dialeto']} por {b['fonte']}")

    # 2. URL de SQL Server, incluindo jTDS.
    for url in ("jdbc:sqlserver://srv:1433;databaseName=SANKHYA",
                "jdbc:jtds:sqlserver://srv:1433/SANKHYA"):
        b = C.bloco_banco(ev(url=url))
        if b["dialeto"] != "sqlserver":
            falhar(f"URL '{url[:28]}' nao resolveu para sqlserver: {b['dialeto']}")

    # 3. Sem URL, o banner decide.
    b = C.bloco_banco(ev(banner="Microsoft SQL Server 2019 (RTM-CU16)"))
    if b["dialeto"] != "sqlserver" or b["fonte"] != "banner do banco no server.log":
        falhar(f"banner sozinho nao decidiu: {b['dialeto']} por {b['fonte']}")

    # 4. Fontes discordando: a URL prevalece e o conflito e registrado.
    b = C.bloco_banco(ev(url="jdbc:oracle:thin:@srv:1521/ORCL",
                         banner="Microsoft SQL Server 2019 (RTM-CU16)"))
    if b["dialeto"] != "oracle":
        falhar(f"conflito nao resolveu pela URL: {b['dialeto']}")
    if not b.get("conflito"):
        falhar("URL e banner divergentes sem campo conflito")

    # 5. Nada identificavel: dialeto None, e nenhum script aplicavel.
    b = C.bloco_banco(ev())
    if b["dialeto"] is not None:
        falhar(f"dialeto inventado sem fonte alguma: {b['dialeto']}")
    if b["scripts"].get("aplicaveis"):
        falhar("script aplicavel com dialeto indefinido")
    if not b["scripts"].get("lacunas"):
        falhar("dialeto indefinido sem lacunas registradas")

    # 6. H2 e o banco interno do servidor, nunca o banco do cliente.
    b = C.bloco_banco(ev(carregados=("org.h2.Driver",)))
    if b["dialeto"] is not None:
        falhar(f"driver interno H2 tratado como banco do cliente: {b['dialeto']}")

    # 7. Driver unico carregado como ultimo recurso.
    b = C.bloco_banco(ev(carregados=("oracle.jdbc.OracleDriver", "org.h2.Driver")))
    if b["dialeto"] != "oracle":
        falhar(f"driver unico nao decidiu: {b['dialeto']}")

    # 8. Dois dialetos e nada mais: nao decide, e nao chuta.
    b = C.bloco_banco(ev(carregados=("oracle.jdbc.OracleDriver",
                                     "com.microsoft.sqlserver.jdbc.SQLServerDriver")))
    if b["dialeto"] is not None:
        falhar(f"dois drivers e nenhuma outra fonte deveriam nao decidir: {b['dialeto']}")

    # 9. Nunca versao do banco a partir da versao do driver.
    b = C.bloco_banco(ev(url="jdbc:oracle:thin:@srv:1521/ORCL",
                         carregados=("oracle.jdbc.OracleDriver",)))
    if b["versao"] is not None:
        falhar(f"versao do banco inferida sem banner: {b['versao']}")

    # 10. Todo arquivo do catalogo existe, e DDL sempre traz o tipo certo.
    try:
        with open(C.CATALOGO_SQL, encoding="utf-8") as f:
            cat = json.load(f)
    except (OSError, ValueError) as e:
        falhar(f"catalogo.json nao lido: {type(e).__name__}: {e}")
        return falhas

    pasta = os.path.dirname(C.CATALOGO_SQL)
    ids = set()
    for item in cat.get("itens", []):
        if item["id"] in ids:
            falhar(f"id repetido no catalogo: {item['id']}")
        ids.add(item["id"])
        if item.get("tipo") not in ("leitura", "ddl", "objeto"):
            falhar(f"tipo invalido em {item['id']}: {item.get('tipo')}")
        arquivos = item.get("arquivos") or {}
        if not arquivos:
            falhar(f"item sem arquivo em dialeto algum: {item['id']}")
        for dialeto, nome in arquivos.items():
            if dialeto not in C.DIALETOS:
                falhar(f"dialeto desconhecido em {item['id']}: {dialeto}")
            if not os.path.exists(os.path.join(pasta, nome)):
                falhar(f"arquivo do catalogo nao existe: {nome} ({item['id']})")
            if not nome.startswith(dialeto):
                falhar(f"nome de arquivo nao comeca pelo dialeto: {nome} ({dialeto})")
        for dialeto in arquivos:
            if (item.get("origem") or {}).get(dialeto) not in ("checklist", "skill"):
                falhar(f"origem invalida em {item['id']}/{dialeto}")
        for dialeto, dep in (item.get("dependencia") or {}).items():
            if not os.path.exists(os.path.join(pasta, dep)):
                falhar(f"dependencia nao existe: {dep} ({item['id']})")

    # 11. Cada dialeto conhecido tem de render pelo menos um script.
    for dialeto in C.DIALETOS:
        s = C._scripts_do_dialeto(dialeto)
        if not s.get("aplicaveis"):
            falhar(f"nenhum script aplicavel para {dialeto}")

    return falhas


def main():
    falhas = []

    for linha, esperado in CASOS_POSITIVOS:
        obtido = rotulos(linha)
        if obtido != esperado:
            falhas.append(f"esperado {sorted(esperado)}, obtido {sorted(obtido)}\n"
                          f"      linha: {linha[:90].decode('latin-1')}")

    for nome, linha in CASOS_NEGATIVOS:
        obtido = rotulos(linha)
        if obtido:
            falhas.append(f"falso positivo em '{nome}': {sorted(obtido)}")

    # Todo padrao de SINAIS precisa ser alcancavel pelo gatilho, senao a
    # ocorrencia e descartada sem aviso.
    cobertos = {r for _, esperado in CASOS_POSITIVOS for r in esperado}
    sem_caso = [n for n, _ in C.SINAIS if n not in cobertos]
    if sem_caso:
        falhas.append(f"sinais sem caso de teste: {sem_caso}")

    # Detectores fora do conjunto de sinais.
    if not C.P_DRIVER.search(
            b'WFLYJCA0004: Deploying JDBC-compliant driver class '
            b'oracle.jdbc.OracleDriver (version 19.23)'):
        falhas.append("P_DRIVER nao casa a linha de deploy de driver")
    if not C.P_BANCO.search(
            b'Oracle Database 19c EE Extreme Perf Release 19.0.0.0.0 - Production\n'):
        falhas.append("P_BANCO nao casa o banner do Oracle")
    if not C.P_CONTINUACAO.match(b'\tat java.lang.Thread.run(Thread.java:748)'):
        falhas.append("P_CONTINUACAO nao reconhece linha de stacktrace")
    if C.P_CONTINUACAO.match(b'java.lang.OutOfMemoryError: Java heap space'):
        falhas.append("P_CONTINUACAO trata primeira linha de excecao como continuacao")

    # Frame de pilha nao declara excecao. `SendErrorPageHandler` termina em "Error" e
    # ja virou a "excecao mais frequente" de um relatorio, com 59 mil ocorrencias.
    if not C.P_FRAME.match(b'	at io.undertow.servlet@2.2.5.Final//io.undertow.servlet'
                           b'.handlers.SendErrorPageHandler.handleRequest(Send.java:52)'):
        falhas.append("P_FRAME nao reconhece frame de pilha com cabecalho de stderr")
    if not C.P_FRAME.match(b'at br.com.sankhya.Foo.bar(Foo.java:1)'):
        falhas.append("P_FRAME nao reconhece frame sem indentacao")
    if C.P_FRAME.match(b'Caused by: java.sql.SQLTimeoutException: ORA-01013'):
        falhas.append("P_FRAME descarta linha `Caused by:`, que declara a excecao real")
    if C.P_FRAME.match(b'java.lang.OutOfMemoryError: Java heap space'):
        falhas.append("P_FRAME descarta a primeira linha da excecao")

    falhas.extend(testar_monitor())
    falhas.extend(testar_banco())

    if falhas:
        print(f"FALHOU: {len(falhas)} problema(s)\n")
        for f in falhas:
            print("  - " + f)
        return 1

    print(f"OK  {len(CASOS_POSITIVOS)} casos positivos, "
          f"{len(CASOS_NEGATIVOS)} negativos, {len(C.SINAIS)} sinais cobertos, "
          f"pacote sintetico do monitor conferido, "
          f"{len(C.DIALETOS)} dialetos e o catalogo de scripts conferidos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
