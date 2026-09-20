#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor de metricas do pacote de log do Sankhya (server.log_AAAAMMDDHHMMSS.zip).

Le o pacote por streaming: nada e descompactado em disco, mesmo com 2,5 GB de log.
Gera dois arquivos:
  evidencias.json  numeros completos, para o gerador do documento
  resumo.md        digest curto, para leitura pelo analista/modelo

Uso:
  python coletar_metricas.py --pacote server.log_20260901233905.zip --saida ./analise
  python coletar_metricas.py --pacote ./pasta_de_log_extraida --saida ./analise --rapido

Sem dependencia externa: so a biblioteca padrao.
"""

import argparse
import io
import json
import os
import re
import struct
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coletar_monitor  # noqa: E402  pacote do Monitor de Consultas

ENC = "cp1252"          # file.encoding do WildFly Sankhya (ISO-8859-1/Cp1252)
BLOCO = 1 << 24         # 16 MB por leitura

# ---------------------------------------------------------------- limiares
# Origem: "Checklist de problemas de performance - Service Desk" (Sankhya).
# Tempo medio por execucao, em ms. Elevacao de ate 20% e tolerada.
LIMITES_DML = {
    ("TGFCAB", "INSERT"): 200, ("TGFCAB", "UPDATE"): 100, ("TGFCAB", "DELETE"): 350,
    ("TGFITE", "INSERT"): 200, ("TGFITE", "UPDATE"): 100, ("TGFITE", "DELETE"): 200,
    ("TGFFIN", "INSERT"): 150, ("TGFFIN", "UPDATE"): 100, ("TGFFIN", "DELETE"): 200,
    ("STP_CONFIRMANOTA2", "STP"): 300,
    ("STP_NUMERAR_NOTA2", "STP"): 200,
    ("STP_SET_SESSION", "STP"): 10,
    ("STP_SET_SESSION2", "STP"): 10,
}
TOLERANCIA = 1.20       # +20% ainda e aceitavel, conforme o checklist

# Objeto sem limiar oficial: so vira achado se passar destes cortes.
CORTE_MEDIA_MS = 1000       # media por execucao acima disso e lenta por si so
CORTE_TEMPO_TOTAL_MS = 60000  # objeto que consome mais de 1 min/periodo pesa no todo

OP_DML = {"0": "INSERT", "1": "UPDATE", "2": "DELETE", "3": "STP"}

NIVEIS_ERRO = (b"ERROR", b"FATAL", b"SEVERE")

# ---------------------------------------------------------------- padroes
# Um unico regex cobre os dois formatos do pacote: `server.log` traz a data na
# linha; o stdout do procrun so traz a hora (a data vem do nome do arquivo).
# Unificar evita uma segunda passada de regex em cada uma das milhoes de linhas.
P_CAB = re.compile(
    rb"^(?:(\d{4})-(\d{2})-(\d{2}) )?(\d{2}):(\d{2}):(\d{2}),(\d{3}) +([A-Z]+) +"
    rb"(?:\[([^\]]*)\] *)?(?:\(([^)]*)\) *)?(.*)$", re.S)
G_ANO, G_MES, G_DIA, G_H, G_MI, G_S, G_MS, G_NIVEL, G_LOGGER, G_THREAD, G_MSG = range(1, 12)

P_DATA_NOME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
P_DATA_NOME_COMPACTA = re.compile(r"(\d{4})(\d{2})(\d{2})")

P_ORA = re.compile(rb"ORA-(\d{5})")
P_EXCECAO = re.compile(rb"((?:[a-zA-Z_$][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error|Throwable))(?::\s*(.{0,180}))?")
P_TEMPO_JOB = re.compile(rb"(?:Tempo (?:de )?execucao|Tempo de execu\xe7\xe3o)[:\s]+(\d+)\s*ms")
P_MONITOR_QUERY = re.compile(rb"##ID_\d{0,6}## tempo: (\d+)")

# Driver JDBC carregado pelo WildFly, e a versao que ele mesmo declara.
P_DRIVER = re.compile(rb"WFLYJCA0004: Deploying JDBC-compliant driver class ([\w.$]+) \(version ([\d.]+)\)")
# Banner do banco. So aparece quando o driver o registra no log.
P_BANCO = re.compile(rb"(Oracle Database .{0,90}?|Microsoft SQL Server .{0,60}?)(?:\r|\n|$)")
# JAR de driver declarado no modulo mas ausente ou corrompido.
P_DRIVER_INVALIDO = re.compile(rb"([\w.\-]+\.jar)\s+does not point to a valid jar")

# O WildFly emite cada linha de stacktrace como uma entrada ERROR [stderr] com
# cabecalho proprio. Contar todas como erro leva a numeros como "67% do log e
# erro", que descrevem o formato do log e nao a saude do ambiente. Estas sao as
# linhas de continuacao: elas pertencem ao evento anterior, nao sao eventos.
P_CONTINUACAO = re.compile(rb"^[\s	]|^(?:at |Caused by:|\.\.\. \d+ more|Suppressed:)")

# Linha de frame de pilha. Ela NUNCA declara excecao: o nome de classe que aparece
# nela e o do metodo em execucao. Sem esta exclusao, `at ...SendErrorPageHandler
# .handleRequest(...)` casa P_EXCECAO (termina em "Error") e o relatorio ganha uma
# "excecao" chamada `io.undertow.servlet.handlers.SendError` com dezenas de milhares
# de ocorrencias — que nao existe. `Caused by:` fica de fora da exclusao de
# proposito: essa linha declara a excecao real da cadeia.
P_FRAME = re.compile(rb"^\s*at \S+\(")

# Sinais nomeados. Um so regex alternado com grupos nomeados: aplicar 16 regex
# separados em cada linha custa 16 varreduras por linha e domina o tempo total
# num arquivo de 2 GB.
SINAIS = [
    ("oom_heap",        rb"OutOfMemoryError: Java heap space"),
    ("oom_outro",       rb"OutOfMemoryError"),  # so quando nao e "Java heap space"
    ("gc_overhead",     rb"GC overhead limit exceeded"),
    ("full_gc",         rb"Full GC"),
    ("deadlock_java",   rb"[Dd]eadlock|DEADLOCK"),
    ("timeout_socket",  rb"SocketTimeoutException"),
    ("timeout_query",   rb"[Qq]uery [Tt]imeout|timeout de consulta|ORA-01013"),
    ("timeout_txn",     rb"[Tt]ransaction.{0,20}timed? ?out|ARJUNA0161"),
    ("datapager_lento", rb"demorou muito a ser consumida"),
    ("pool_exausto",    rb"IJ000453|No ManagedConnections available|IJ000655"),
    ("pool_validacao",  rb"validateConnections"),
    ("conexao_fechada", rb"Closed Connection|ORA-17008|onnection is closed"),
    ("sessao_expirada", rb"ORA-02396|ORA-01012"),
    ("epoll_hang",      rb"epoll.{0,12}hang"),
    ("deploy_timeout",  rb"WFLYCTL0348"),
    ("erro_undertow",   rb"UT005023|UT005071"),
    # WFLYSRV0049 sai uma unica vez por inicializacao do servidor. Nao juntar
    # outras mensagens de boot aqui: o numero e lido como "quantos reinicios",
    # e qualquer padrao a mais infla a conta.
    ("servidor_subindo", rb"WFLYSRV0049"),
]

# Linha que ECOA configuracao nunca e evento, e essa e a familia inteira de
# falso positivo desta parte do coletor: o que casa e o NOME do argumento.
#
# Num pacote de cliente, tres linhas reais produziram dois achados falsos:
#   DEBUG [org.jboss.as.config] ... VM Arguments: ... -XX:+HeapDumpOnOutOfMemoryError
#                                                 ... -Depoll.hang.log=false
#   \tepoll.hang.log = false
#   \tepoll.hang.timeout = 180000
# Viraram "estouro de memoria: 2 ocorrencias" e "trava de epoll: 4 ocorrencias".
#
# Tratar isso por exclusao de rotulo e enxugar gelo: cada argumento novo com
# nome de erro abre um buraco. O corte e antes, na linha.
P_LINHA_CONFIG = re.compile(
    rb"VM Arguments"                      # dump de argumentos do WildFly
    rb"|JAVA_OPTS"                        # eco do standalone.conf
    rb"|\[org\.jboss\.as\.config\]"       # logger que so imprime configuracao
    rb"|^\s*[\w.\-]+\s*=\s*[^\s=]*\s*$"   # eco `chave = valor`, linha inteira
)

# Exclusoes por rotulo: o padrao casou, mas a linha nao e o evento.
# Sem isso o relatorio ganha achado inventado — e achado inventado num
# diagnostico custa mais caro que achado nao encontrado.
EXCLUSOES_SINAL = {
    # "OutOfMemoryError: Java heap space" e "OutOfMemoryError: GC overhead limit
    # exceeded" ja tem rotulo proprio. Sem esta exclusao a mesma linha conta duas
    # vezes, porque o literal generico casa antes do especifico na mesma linha.
    "oom_outro": (b"Java heap space", b"GC overhead limit exceeded"),
    # nome da classe que PROCURA deadlock, nao um deadlock
    "deadlock_java": (b"DeadlockScanner", b"deadlock scan", b"Deadlock scan"),
    # `-Depoll.hang.log=false` na linha de JAVA_OPTS do boot
    "epoll_hang": (b"-Depoll", b"JAVA_OPTS"),
    # a propria linha de argumentos cita varios timeouts
    "timeout_query": (b"JAVA_OPTS",),
    "timeout_txn": (b"JAVA_OPTS",),
}
P_SINAIS = re.compile(b"|".join(b"(?P<%s>%s)" % (n.encode(), p) for n, p in SINAIS))

# Gatilho: so literais, nenhum quantificador. Rodar P_SINAIS direto em cada linha
# custa ~9x mais, porque a alternancia com `.{0,20}` impede a otimizacao de
# literal do motor e forca backtracking em toda linha que nao casa. Medido em
# 150 MB de stdout: 35,5 s sem gatilho contra 3,9 s com ele.
# Todo padrao de SINAIS precisa ter um literal correspondente aqui, senao a
# ocorrencia e perdida silenciosamente.
P_GATILHO = re.compile(
    rb"imeout|imed|ime out|OutOfMemory|eadlock|EADLOCK|ORA-|consumida|IJ000|"
    rb"ManagedConnections|GC overhead|Full GC|validateConnections|epoll|"
    rb"WFLYCTL0348|UT0050|Closed Connection|onnection is closed|"
    rb"WFLYSRV0049")

# Codigos ORA com leitura direta de performance (checklist + Sankhya-W).
ORA_CONHECIDOS = {
    "00060": "Deadlock detectado no Oracle. Contencao entre sessoes concorrentes.",
    "01013": "Operacao cancelada pelo usuario ou por timeout de query.",
    "04031": "Falta de memoria na shared pool do Oracle.",
    "00257": "Erro de archiver. Area de archive log cheia.",
    "12516": "Listener sem handler disponivel. Numero maximo de processos excedido.",
    "12514": "SID inexistente ou servico do banco parado.",
    "28000": "Conta de banco bloqueada.",
    "28001": "Senha do usuario de banco expirada.",
    "01555": "Snapshot too old. Undo insuficiente para consulta longa.",
    "00054": "Recurso ocupado com NOWAIT. Lock nao liberado.",
    "01438": "Valor maior que a precisao da coluna.",
    "00936": "Expressao ausente. SQL malformado, tipicamente de personalizacao.",
    "00918": "Coluna ambigua. Join sem qualificar a coluna, tipicamente de personalizacao.",
    "00904": "Identificador invalido. Coluna inexistente no objeto.",
    "00942": "Tabela ou view inexistente.",
    "00001": "Violacao de chave unica.",
    "00604": "Erro em SQL recursivo. Costuma acompanhar falha em trigger.",
    "04088": "Erro na execucao de trigger. Sempre acompanha o erro real da trigger.",
    "06512": "Pilha de erro de PL/SQL. Indica a linha, nao a causa.",
    "20101": "Erro levantado por RAISE_APPLICATION_ERROR: regra de negocio no banco.",
    "01017": "Usuario ou senha invalidos.",
    "17008": "Conexao ja fechada em uso.",
}


def agora():
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def limitar(counter, n):
    return [{"chave": k, "ocorrencias": v} for k, v in counter.most_common(n)]


# ------------------------------------------------------------------ fonte
class Fonte:
    """Abstrai pacote .zip e pasta ja extraida sob a mesma interface."""

    def __init__(self, caminho):
        self.caminho = caminho
        self.zip = None
        if os.path.isdir(caminho):
            self.nomes = []
            for raiz, _, arqs in os.walk(caminho):
                for a in arqs:
                    p = os.path.join(raiz, a)
                    self.nomes.append(os.path.relpath(p, caminho).replace("\\", "/"))
            self.comentario = ""
            self._tam = {n: os.path.getsize(os.path.join(caminho, n)) for n in self.nomes}
        else:
            self.zip = zipfile.ZipFile(caminho)
            infos = [i for i in self.zip.infolist() if not i.is_dir()]
            self.nomes = [i.filename for i in infos]
            self._tam = {i.filename: i.file_size for i in infos}
            self.comentario = _decodificar_comentario(self.zip.comment)

    def tamanho(self, nome):
        return self._tam.get(nome, 0)

    def abrir(self, nome):
        if self.zip:
            return self.zip.open(nome)
        return open(os.path.join(self.caminho, nome), "rb")

    def ler(self, nome, limite=None):
        with self.abrir(nome) as f:
            return f.read() if limite is None else f.read(limite)

    def texto(self, nome, limite=None):
        return self.ler(nome, limite).decode(ENC, "replace")


# ------------------------------------------------------------- ambiente
def bloco_ambiente(fonte):
    """Cabecalho do pacote + version.properties + mge-ds.xml + argumentos da VM."""
    amb = {"comentario_pacote": fonte.comentario.strip()}

    campos = {
        "empresa": r"Empresa:\s*(.+)",
        "versao_sankhyaw": r"Versao do SankhyaW:\s*(.+)",
        "navegador": r"Navegador:\s*(.+)",
        "sistema_operacional": r"Sistema Operacional:\s*(.+)",
        "charset": r"CharSet padr[^:]*:\s*(.+)",
        "encoding_arquivo": r"Cod\.Arquivo \(encoding\):\s*(.+)",
        "dir_servidor": r"Dir\. servidor aplica[^:]*:\s*(.+)",
        "versao_servidor": r"Vers[^:]*o do servidor de aplica[^:]*:\s*(.+)",
        "java": r"Java:\s*(.+)",
        "jvm": r"JVM:\s*(.+)",
        "memoria_heap": r"Memoria Heap:\s*(.+)",
        "argumentos_vm": r"Argumentos da VM:\s*(.+)",
    }
    txt = fonte.comentario
    for chave, padrao in campos.items():
        m = re.search(padrao, txt)
        if m:
            amb[chave] = m.group(1).strip()

    # Heap: "4257.4921875 / 4995.375 MB" -> usado, total, percentual
    m = re.search(r"([\d.]+)\s*/\s*([\d.]+)\s*MB", amb.get("memoria_heap", ""))
    if m:
        usado, total = float(m.group(1)), float(m.group(2))
        amb["heap_usado_mb"] = round(usado, 1)
        amb["heap_total_mb"] = round(total, 1)
        amb["heap_uso_pct"] = round(usado / total * 100, 1) if total else None

    args = amb.get("argumentos_vm", "")
    lista = [a.strip() for a in args.split(",") if a.strip()]
    amb["vm_args"] = lista
    amb["vm_args_map"] = {}
    for a in lista:
        if a.startswith("-D") and "=" in a:
            k, v = a[2:].split("=", 1)
            amb["vm_args_map"][k] = v
    amb["xms_mb"] = _mem_arg(lista, "-Xms")
    amb["xmx_mb"] = _mem_arg(lista, "-Xmx")
    amb["gc"] = next((a for a in lista if "GC" in a and a.startswith("-XX:+Use")), None)

    if "version.properties" in fonte.nomes:
        amb["modulos"] = {}
        for linha in fonte.texto("version.properties").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, v = linha.split("=", 1)
                amb["modulos"][k.strip()] = v.strip()

    if "mge-ds.xml" in fonte.nomes:
        ds = fonte.texto("mge-ds.xml")
        amb["datasource"] = {
            "url": _tag(ds, "connection-url"),
            "driver": _tag(ds, "driver"),
            "min_pool": _tag(ds, "min-pool-size"),
            "max_pool": _tag(ds, "max-pool-size"),
            "prefill": _tag(ds, "prefill"),
        }
        # a URL pode carregar host/porta/SID: nao guardar credencial
        amb["datasource"] = {k: v for k, v in amb["datasource"].items() if v}

    if "parametros.properties" in fonte.nomes:
        params = {}
        for linha in fonte.texto("parametros.properties").splitlines():
            if "=" in linha and not linha.strip().startswith("#"):
                k, v = linha.split("=", 1)
                params[k.strip()] = v.strip()
        amb["qtd_parametros"] = len(params)
        interesse = ["SERVERHOSTSCHED", "QTDENVIOMSGJOB", "MSDINTAGENDADOR",
                     "TEMPOSESSAO", "QTDMAXSESSAO", "USAPROCNUM"]
        amb["parametros_relevantes"] = {k: params[k] for k in interesse if k in params}
    return amb


# ------------------------------------------------- ciclo de vida do servidor
# Padroes do que uma analise real teve de escavar a mao no zip. Todos casam uma
# unica linha, com literal proprio no gatilho, e nenhum depende de contexto.
#
# WFLYSRV0025 = subida limpa, WFLYSRV0026 = subida com erro. As duas trazem o
# tempo em ms e a contagem de servicos, e sao a unica medida de indisponibilidade
# por reinicio que o pacote oferece.
# CUIDADO: nao subtrair `iniciados` de `total` para achar os falhos. O total
# inclui os servicos lazy, passive e on-demand, que nunca iniciam por serem sob
# demanda. Num pacote real a subtracao dava 534 falhos contra os 36 que o
# proprio WildFly declara, e 534 e numero de relatorio errado.
P_BOOT = re.compile(
    rb"WFLYSRV002[56]: (.{0,90}?) started (\(with errors\) )?in (\d+)ms"
    rb"(?: - Started (\d+) of (\d+) services"
    rb"(?:\s*\((\d+) services failed[^)]*?"
    rb"(?:,\s*(\d+) services are lazy[^)]*)?\))?)?")

# Linha do sumario de servicos que nao subiram. O nome do deployment esta entre
# aspas, e a causa vem logo depois dos dois-pontos.
P_SERVICO_FALHO = re.compile(
    rb'service jboss\.deployment\.(?:subunit|unit)\."([^"]+)"'
    rb'(?:\."([^"]+)")?\.([\w-]+): (.{0,80})')

# WFLYSRV0010 = Deployed, WFLYSRV0016 = Replaced deployment. Republicacao a
# quente e o gatilho do vazamento de thread e de classloader.
P_REDEPLOY = re.compile(rb'WFLYSRV001[06]: (?:Replaced deployment|Deployed) "([^"]+)"')

# Falha de script na migracao de dicionario ou de scripts do modulo. O nome do
# modulo e a etapa vem no prefixo `[modulo - ddmigration]` da propria linha.
#
# CUIDADO medido: `ScriptMigrationProcessor` sozinho NAO serve de gatilho. Esse
# logger emite milhares de linhas INFO de progresso, e conta-las como falha deu
# 2.194 num pacote onde as falhas reais eram 222. So entra linha que declara a
# falha: a mensagem literal, ou o logger em nivel ERROR.
P_MIGRACAO = re.compile(rb"\[([\w.-]+) - (ddmigration|scriptmigration)\]")

# Thread de modulo que nao encerra na republicacao: vazamento acumulado.
P_THREAD_ORFA = rb"Erro ao interromper thread"


def _decodificar_comentario(bruto):
    """Decodifica o comentario do zip, que NAO segue o encoding do resto do pacote.

    Medido num pacote real: os arquivos de log vem em ISO-8859-1, mas o
    comentario vem em UTF-8. Decodificar tudo com ENC transformava `Esteriotipo`
    em `EsteriÃ³tipo`, e com isso o estereotipo da base (TESTE ou producao) e a
    data de importacao do dicionario simplesmente nao casavam com o padrao.
    Os campos ASCII do cabecalho funcionavam, e por isso o defeito passou.

    UTF-8 primeiro, ISO-8859-1 como reserva: e nesta ordem porque UTF-8 invalido
    falha alto, enquanto ISO-8859-1 aceita qualquer byte e nunca acusa o erro.
    """
    if not bruto:
        return ""
    try:
        return bruto.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        pass
    try:
        return bruto.decode(ENC, "replace")
    except Exception:
        return ""


# ------------------------------------------------------------- diagnostico
# O comentario do zip traz um bloco "Informacoes de diagnostico" que o proprio
# Sankhya monta, com o valor medido E o limite recomendado lado a lado. Era a
# fonte mais valiosa do pacote e o coletor a ignorava por completo.
#
# O custo dessa omissao foi medido: numa analise real, descobrir que o achado
# automatico "heap a 100%" era falso exigiu abrir o comentario a mao. A resposta
# estava aqui, em "Tempo gasto com GC: 0.09% | Recomendado: Maximo 2%".
#
# Formato de cada linha: `Rotulo: valor | Recomendado: limite`. A leitura e
# generica de proposito: versao nova do Sankhya acrescenta linha, e linha nova
# aparece sozinha no JSON em vez de exigir mexer neste arquivo.
P_DIAG = re.compile(r"^([^:|]{3,60}):\s*(.*?)\s*(?:\|\s*Recomendado:\s*(.*?))?\s*$")

# Rotulos cujo numero a analise usa direto. O resto fica na lista generica.
DIAG_NUMERICOS = {
    "tempo gasto com gc": ("gc_pct", r"([\d.,]+)\s*%"),
    "tempo de cpu utilizado": ("cpu_pct", r"([\d.,]+)\s*%"),
    "relacao mem.fisica x alocada": ("memoria_ratio_pct", r"([\d.,]+)\s*%"),
    "memoria do espaco de codigo": ("cache_codigo_mb", r"^(\d+)"),
    "tamanho do pool de conexoes": ("pool_tamanho", r"^(\d+)"),
}


def _num(txt, padrao):
    if not txt:
        return None
    m = re.search(padrao, txt)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def bloco_diagnostico(fonte):
    """Le o bloco de diagnostico e o registro de base do comentario do zip.

    Devolve o valor medido junto com o limite que o proprio sistema recomenda.
    Sem o par, o numero nao diz se e problema: 0,09% de GC e 26% de memoria
    sao normais, e sem o "Recomendado: Maximo 2%" ao lado o leitor nao sabe.
    """
    txt = fonte.comentario
    if not txt:
        return None

    d = {}

    # bloco de diagnostico, entre o titulo e a linha em branco dupla seguinte
    itens, chaves = [], {}
    dentro = False
    for linha in txt.splitlines():
        if linha.strip().lower().startswith("informacoes de diagnostico"):
            dentro = True
            continue
        if not dentro:
            continue
        if linha.strip().lower().startswith("parametros de performance"):
            break
        m = P_DIAG.match(linha.strip())
        if not (m and linha.strip()):
            continue
        rot, valor, rec = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "").strip()
        if not valor:
            continue
        itens.append({"item": rot, "valor": valor, "recomendado": rec or None})
        alvo = DIAG_NUMERICOS.get(rot.lower())
        if alvo:
            chaves[alvo[0]] = _num(valor, alvo[1])
    if itens:
        d["itens"] = itens
        d.update(chaves)

    # Espera por conexao: e o numero que decide se o pool esta em disputa, e
    # nao o pico de conexoes. Pico alto com espera baixa nao e gargalo.
    esp = next((x["valor"] for x in itens if x["item"].lower().startswith("espera por conexao")), None)
    if esp:
        d["espera_conexao_ms_media"] = _num(esp, r"Media:\s*([\d.,]+)")
        d["espera_conexao_ms_max"] = _num(esp, r"Max\.?:\s*([\d.,]+)")

    trg = next((x for x in itens if "trigger" in x["item"].lower()), None)
    if trg:
        d["triggers_pendentes"] = trg["valor"] != (trg["recomendado"] or "")

    # Registro de base: o estereotipo diz se o pacote e de producao ou de teste.
    # Analisar lentidao de producao sobre pacote de teste ja aconteceu.
    for chave, padrao in (
        ("estereotipo", r"Esteri[oó]tipo da Base de Dados:\s*(.+)"),
        ("host", r"^Host:\s*(.+)"),
        ("versao_atualizacao_bd", r"Vers[aã]o de atualiza[cç][aã]o do BD:\s*(.+)"),
        ("dd_data_exportacao", r"Data de Exporta[cç][aã]o:\s*(.+)"),
        ("dd_data_importacao", r"Data de Importa[cç][aã]o:\s*(.+)"),
    ):
        m = re.search(padrao, txt, re.M)
        if m:
            d[chave] = m.group(1).strip()
    if d.get("estereotipo"):
        d["producao"] = d["estereotipo"].strip().upper() not in ("TESTE", "TREINA", "TREINAMENTO")

    # Parametros de performance, ja separados pelo proprio pacote.
    params, dentro = {}, False
    for linha in txt.splitlines():
        if linha.strip().lower().startswith("parametros de performance"):
            dentro = True
            continue
        if not dentro:
            continue
        if linha.strip().lower().startswith("geracao do arquivo"):
            break
        if ":" in linha:
            k, v = linha.split(":", 1)
            if k.strip():
                params[k.strip()] = v.strip()
    if params:
        d["parametros_performance"] = params

    return d or None


def _mem_arg(lista, prefixo):
    for a in lista:
        if a.startswith(prefixo):
            v = a[len(prefixo):].strip().lower()
            try:
                if v.endswith("g"):
                    return int(float(v[:-1]) * 1024)
                if v.endswith("m"):
                    return int(float(v[:-1]))
                if v.endswith("k"):
                    return int(float(v[:-1]) / 1024)
                return int(int(v) / 1048576)
            except ValueError:
                return None
    return None


def _tag(xml, nome):
    """Le uma tag exata. O `[^>]*` ingenuo faz <driver> casar com <driver-class>."""
    m = re.search(r"<%s(?:\s[^>]*)?>(.*?)</%s>" % (nome, nome), xml, re.S)
    return m.group(1).strip() if m else None


# ------------------------------------------------------------------ logs
class AcumuladorLog:
    """Agrega um conjunto de arquivos de log da aplicacao."""

    def __init__(self):
        self.linhas = 0
        self.bytes = 0
        self.por_nivel = Counter()
        self.eventos_erro = 0          # erro sem as linhas de continuacao
        self.linhas_stacktrace = 0     # continuacao emitida como entrada propria
        self.por_hora = Counter()          # 'AAAA-MM-DD HH' -> entradas
        self.erros_por_hora = Counter()
        self.loggers = Counter()
        self.threads_erro = Counter()
        self.excecoes = Counter()
        self.excecoes_amostra = {}
        self.excecoes_janela = {}          # assinatura -> [primeira, ultima]
        self.ora = Counter()
        self.ora_amostra = {}
        self.sinais = Counter()
        self.sinais_amostra = defaultdict(list)
        self.jobs = defaultdict(lambda: {"execucoes": 0, "tempo_ms": 0, "max_ms": 0})
        self.query_monitor = []
        self.drivers = {}              # classe -> versao declarada
        self.banco = Counter()         # banner do banco
        self.drivers_invalidos = Counter()
        # Ciclo de vida do servidor. Estes quatro custam uma comparacao de
        # literal por linha e substituem quatro escavacoes manuais que uma
        # analise real precisou fazer no zip.
        self.boots = []                    # conclusao de cada subida
        self.servicos_falhos = Counter()   # deployment -> causa resumida
        self.redeploys = Counter()         # modulo -> republicacoes
        self.redeploys_por_dia = Counter()
        self.migracao_falhas = Counter()   # modulo -> falhas de script
        self.threads_nao_encerradas = Counter()   # dia -> falhas de interrupcao
        self.primeiro_ts = None
        self.ultimo_ts = None
        self.arquivos = []
        self.truncado = False

    def marcar_ts(self, ts):
        if ts is None:
            return
        if self.primeiro_ts is None or ts < self.primeiro_ts:
            self.primeiro_ts = ts
        if self.ultimo_ts is None or ts > self.ultimo_ts:
            self.ultimo_ts = ts


def data_base_do_nome(nome):
    """Extrai a data inicial de um arquivo cujo cabecalho nao tem data."""
    base = os.path.basename(nome)
    m = P_DATA_NOME.search(base)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = P_DATA_NOME_COMPACTA.search(base)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def varrer_log(fonte, nome, acc, limite_bytes=None):
    """Percorre um arquivo de log e alimenta o acumulador.

    Trabalha em bytes: decodificar 20 milhoes de linhas para depois descartar
    quase todas custa minutos a mais sem nada em troca.
    """
    tamanho = fonte.tamanho(nome)
    acc.arquivos.append({"arquivo": nome, "bytes": tamanho})
    data_base = data_base_do_nome(nome)
    hora_anterior = None
    dia_extra = 0
    lidos = 0
    resto = b""
    ctx_thread = b""
    ctx_ts = None

    with fonte.abrir(nome) as f:
        while True:
            bloco = f.read(BLOCO)
            if not bloco:
                break
            if limite_bytes:
                restante = limite_bytes - lidos
                if restante <= 0:
                    acc.truncado = True
                    break
                if len(bloco) > restante:
                    acc.truncado = True
                    bloco = bloco[:restante]
            lidos += len(bloco)
            acc.bytes += len(bloco)
            dados = resto + bloco
            linhas = dados.split(b"\n")
            resto = linhas.pop()
            for linha in linhas:
                acc.linhas += 1
                if not linha:
                    continue
                if linha[-1] == 13:                 # \r
                    linha = linha[:-1]
                    if not linha:
                        continue

                corpo = linha
                ts = None
                # Cabecalho sempre comeca por digito. A maioria esmagadora das
                # linhas de um log Java e continuacao de stacktrace ("\tat ..."):
                # este teste as descarta antes de qualquer regex.
                if 48 <= linha[0] <= 57:
                    m = P_CAB.match(linha)
                else:
                    m = None

                if m:
                    nivel = m.group(G_NIVEL)
                    logger = m.group(G_LOGGER)
                    thread = m.group(G_THREAD)
                    corpo = m.group(G_MSG)
                    h, mi, s = int(m.group(G_H)), int(m.group(G_MI)), int(m.group(G_S))
                    if m.group(G_ANO):
                        try:
                            ts = datetime(int(m.group(G_ANO)), int(m.group(G_MES)),
                                          int(m.group(G_DIA)), h, mi, s)
                        except ValueError:
                            ts = None
                    elif data_base:
                        segundos = h * 3600 + mi * 60 + s
                        if hora_anterior is not None and segundos < hora_anterior - 3600:
                            dia_extra += 1          # a hora retrocedeu: virou o dia
                        hora_anterior = segundos
                        try:
                            ts = data_base + timedelta(days=dia_extra, seconds=segundos)
                        except (ValueError, OverflowError):
                            ts = None

                    acc.por_nivel[nivel.decode(ENC, "replace")] += 1
                    if logger:
                        acc.loggers[logger.decode(ENC, "replace")] += 1
                    ctx_thread = thread or b""
                    ctx_ts = ts
                    acc.marcar_ts(ts)

                    erro = nivel in NIVEIS_ERRO
                    continuacao = erro and bool(P_CONTINUACAO.match(corpo))
                    if continuacao:
                        acc.linhas_stacktrace += 1
                    elif erro:
                        acc.eventos_erro += 1

                    if ts and not continuacao:
                        chave = ts.strftime("%Y-%m-%d %H")
                        acc.por_hora[chave] += 1
                        if erro:
                            acc.erros_por_hora[chave] += 1
                    if erro and not continuacao and ctx_thread:
                        acc.threads_erro[ctx_thread.decode(ENC, "replace")] += 1

                _classificar(acc, linha, corpo, ctx_thread, ctx_ts or ts)

    if resto:
        acc.linhas += 1


def _ciclo_de_vida(acc, linha, corpo, ts):
    """Subida do servidor, servico falho, republicacao e falha de migracao.

    Cada bloco abre com um teste de literal barato. Sem eles, quatro perguntas
    que toda analise faz ("quanto demora para subir", "o que nao subiu", "quantas
    republicacoes", "a migracao falhou") so se respondem escavando o zip a mao.
    """
    dia = ts.strftime("%Y-%m-%d") if ts else None

    if b"WFLYSRV002" in linha:
        m = P_BOOT.search(linha)
        if m:
            acc.boots.append({
                "servidor": m.group(1).decode(ENC, "replace").strip(),
                "com_erros": bool(m.group(2)),
                "tempo_ms": int(m.group(3)),
                "servicos_iniciados": int(m.group(4)) if m.group(4) else None,
                "servicos_total": int(m.group(5)) if m.group(5) else None,
                # declarado pelo servidor, nunca calculado por subtracao
                "servicos_falhos": int(m.group(6)) if m.group(6) else None,
                "servicos_sob_demanda": int(m.group(7)) if m.group(7) else None,
                "quando": ts.isoformat(sep=" ") if ts else None,
            })

    # O sumario de servicos falhos vem em bloco, uma linha por servico. As
    # linhas nao tem cabecalho proprio, entao o teste tem de ser na linha crua.
    if b"jboss.deployment." in linha and (b"failed" in linha or b"Failed" in linha
                                          or b"WFLYSRV0153" in linha
                                          or b"missing" in linha):
        m = P_SERVICO_FALHO.search(linha)
        if m:
            unidade = m.group(1).decode(ENC, "replace")
            sub = m.group(2).decode(ENC, "replace") if m.group(2) else None
            fase = m.group(3).decode(ENC, "replace")
            alvo = f"{unidade}/{sub}" if sub else unidade
            acc.servicos_falhos[f"{alvo} [{fase}]"] += 1

    if b"WFLYSRV001" in linha:
        m = P_REDEPLOY.search(linha)
        if m:
            acc.redeploys[m.group(1).decode(ENC, "replace")] += 1
            if dia:
                acc.redeploys_por_dia[dia] += 1

    falha_migracao = (b"Erro na execu" in linha
                      or (b"ScriptMigrationProcessor" in linha and b" ERROR " in linha))
    if falha_migracao:
        m = P_MIGRACAO.search(linha)
        modulo = m.group(1).decode(ENC, "replace") if m else "(sem modulo)"
        etapa = m.group(2).decode() if m else "?"
        acc.migracao_falhas[f"{modulo} [{etapa}]"] += 1

    if P_THREAD_ORFA in linha and dia:
        acc.threads_nao_encerradas[dia] += 1


def _classificar(acc, linha, corpo, thread, ts):
    """Extrai excecao, ORA-, sinal nomeado e tempo de job de uma linha."""
    # o teste vai no CORPO, nao na linha: o WildFly emite cada frame de pilha com
    # cabecalho proprio, e `linha` comeca pela data
    if (b"Exception" in linha or b"Error" in linha) and not P_FRAME.match(corpo):
        m = P_EXCECAO.search(linha)
        if m:
            classe = m.group(1).decode(ENC, "replace")
            msg = (m.group(2) or b"").decode(ENC, "replace").strip()
            assinatura = classe + ((": " + _normalizar(msg)) if msg else "")
            acc.excecoes[assinatura] += 1
            if assinatura not in acc.excecoes_amostra:
                acc.excecoes_amostra[assinatura] = linha[:600].decode(ENC, "replace")
            if ts:
                jan = acc.excecoes_janela.setdefault(assinatura, [ts, ts])
                if ts < jan[0]:
                    jan[0] = ts
                if ts > jan[1]:
                    jan[1] = ts

    if b"ORA-" in linha:
        for m in P_ORA.finditer(linha):
            cod = m.group(1).decode()
            acc.ora[cod] += 1
            if cod not in acc.ora_amostra:
                acc.ora_amostra[cod] = linha[:500].decode(ENC, "replace")

    _ciclo_de_vida(acc, linha, corpo, ts)

    # Eco de configuracao nao gera sinal. Corte antes de P_SINAIS: barato, e
    # fecha a familia toda de falso positivo por nome de argumento.
    m = (P_SINAIS.search(linha)
         if P_GATILHO.search(linha) and not P_LINHA_CONFIG.search(linha)
         else None)
    if m:
        # Uma linha pode disparar mais de um sinal (ex.: oom_heap e oom_qualquer):
        # percorrer todas as ocorrencias mantem a contagem por rotulo correta.
        vistos = set()
        while m:
            rotulo = m.lastgroup
            excl = EXCLUSOES_SINAL.get(rotulo)
            if excl and any(x in linha for x in excl):
                rotulo = None
            if rotulo and rotulo not in vistos:
                vistos.add(rotulo)
                acc.sinais[rotulo] += 1
                if len(acc.sinais_amostra[rotulo]) < 3:
                    acc.sinais_amostra[rotulo].append({
                        "linha": linha[:500].decode(ENC, "replace"),
                        "quando": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else None,
                    })
            m = P_SINAIS.search(linha, m.end())

    if b"empo" in linha and b"ms" in linha:
        m = P_TEMPO_JOB.search(linha)
        if m:
            ms = int(m.group(1))
            rotulo = _rotulo_job(corpo)
            if rotulo is None:
                return
            j = acc.jobs[rotulo]
            j["execucoes"] += 1
            j["tempo_ms"] += ms
            j["max_ms"] = max(j["max_ms"], ms)

    if b"WFLYJCA0004" in linha:
        m = P_DRIVER.search(linha)
        if m:
            acc.drivers[m.group(1).decode()] = m.group(2).decode()

    # Pre-filtro estreito de proposito: "Database" e "SQL Server" soltos aparecem
    # em milhares de linhas de negocio e o custo do regex nao se paga.
    if b"Oracle Database " in linha or b"Microsoft SQL Server " in linha:
        m = P_BANCO.search(linha)
        if m:
            acc.banco[m.group(1).decode(ENC, "replace").strip()] += 1

    if b"valid jar" in linha:
        m = P_DRIVER_INVALIDO.search(linha)
        if m:
            acc.drivers_invalidos[m.group(1).decode()] += 1

    if b"##ID_" in linha:
        m = P_MONITOR_QUERY.search(linha)
        if m and len(acc.query_monitor) < 500:
            acc.query_monitor.append({
                "ms": int(m.group(1)),
                "linha": linha[:400].decode(ENC, "replace"),
                "quando": ts.strftime("%Y-%m-%d %H:%M:%S") if ts else None,
            })


def _normalizar(msg):
    """Colapsa numeros, ids e datas para que o mesmo erro nao vire N assinaturas."""
    s = re.sub(r"\d+", "#", msg)
    s = re.sub(r"[0-9a-fA-F]{16,}", "#", s)
    s = re.sub(r"\s+", " ", s)
    return s[:120].strip()


def _rotulo_job(corpo):
    txt = corpo.decode(ENC, "replace")
    txt = re.sub(r"\s*-\s*Tempo.*$", "", txt, flags=re.I)
    txt = re.sub(r"^\s*>>\s*", "", txt)
    txt = re.sub(r"^(Finalizado|Iniciado)\s+", "", txt, flags=re.I)
    txt = re.sub(r"\d+", "#", txt).strip()
    # Payload XML/JSON que por acaso contem "tempo ... ms" nao e nome de job.
    if not txt or any(c in txt for c in "<>{}\""):
        return None
    return txt[:100]


def bloco_logs(fonte, rapido):
    """Varre os logs de aplicacao.

    Eles ficam na raiz do pacote. `sas-server/`, `dml_stats/`, `.ald/` e
    `bootloader/` tem formato proprio e sao tratados nos blocos respectivos.
    """
    alvos = []
    for n in fonte.nomes:
        if "/" in n:
            continue
        if n.lower().startswith(("server.log", "sankhya_w", "service.")):
            alvos.append(n)
    alvos.sort(key=lambda n: -fonte.tamanho(n))

    limite = (200 << 20) if rapido else None
    acc = AcumuladorLog()
    for n in alvos:
        varrer_log(fonte, n, acc, limite_bytes=limite)

    horas = sorted(acc.por_hora.items())
    pico = acc.por_hora.most_common(1)
    pico_erro = acc.erros_por_hora.most_common(1)
    erros_brutos = sum(v for k, v in acc.por_nivel.items() if k in ("ERROR", "FATAL", "SEVERE"))

    excecoes = []
    for assinatura, qtd in acc.excecoes.most_common(40):
        jan = acc.excecoes_janela.get(assinatura)
        excecoes.append({
            "assinatura": assinatura,
            "ocorrencias": qtd,
            "primeira": jan[0].strftime("%Y-%m-%d %H:%M:%S") if jan else None,
            "ultima": jan[1].strftime("%Y-%m-%d %H:%M:%S") if jan else None,
            "amostra": acc.excecoes_amostra.get(assinatura, ""),
        })

    oracle = []
    for cod, qtd in acc.ora.most_common(30):
        oracle.append({
            "codigo": "ORA-" + cod,
            "ocorrencias": qtd,
            "significado": ORA_CONHECIDOS.get(cod),
            "amostra": acc.ora_amostra.get(cod, ""),
        })

    jobs = []
    for rotulo, j in sorted(acc.jobs.items(), key=lambda x: -x[1]["tempo_ms"])[:30]:
        jobs.append({
            "job": rotulo,
            "execucoes": j["execucoes"],
            "tempo_total_ms": j["tempo_ms"],
            "tempo_medio_ms": round(j["tempo_ms"] / max(j["execucoes"], 1), 1),
            "tempo_max_ms": j["max_ms"],
        })

    return {
        "arquivos": acc.arquivos,
        "linhas": acc.linhas,
        "bytes": acc.bytes,
        "truncado": acc.truncado,
        "periodo": {
            "inicio": acc.primeiro_ts.strftime("%Y-%m-%d %H:%M:%S") if acc.primeiro_ts else None,
            "fim": acc.ultimo_ts.strftime("%Y-%m-%d %H:%M:%S") if acc.ultimo_ts else None,
        },
        "por_nivel": dict(acc.por_nivel),
        "total_erros_brutos": erros_brutos,
        "linhas_stacktrace": acc.linhas_stacktrace,
        "total_eventos_erro": acc.eventos_erro,
        "total_eventos": sum(acc.por_nivel.values()) - acc.linhas_stacktrace,
        "por_hora": [{"hora": h, "entradas": v, "erros": acc.erros_por_hora.get(h, 0)} for h, v in horas],
        # agregado de 24 linhas: sobrevive a separacao da serie detalhada e
        # responde "em que hora do dia isso acontece" sem abrir series.json
        "por_hora_do_dia": _agregar_hora_do_dia(acc),
        "hora_pico": {"hora": pico[0][0], "entradas": pico[0][1]} if pico else None,
        "hora_pico_erros": {"hora": pico_erro[0][0], "erros": pico_erro[0][1]} if pico_erro else None,
        "top_loggers": limitar(acc.loggers, 25),
        "top_threads_erro": limitar(acc.threads_erro, 25),
        "excecoes": excecoes,
        "oracle": oracle,
        "sinais": dict(acc.sinais),
        "sinais_amostra": {k: v for k, v in acc.sinais_amostra.items()},
        "jobs": jobs,
        "monitor_consultas": sorted(acc.query_monitor, key=lambda x: -x["ms"])[:50],
        "drivers_carregados": [{"classe": k, "versao": v} for k, v in sorted(acc.drivers.items())],
        "banco": [{"banner": k, "ocorrencias": v} for k, v in acc.banco.most_common(5)],
        "drivers_invalidos": [{"jar": k, "ocorrencias": v} for k, v in acc.drivers_invalidos.most_common(10)],
        "ciclo_de_vida": {
            "boots": acc.boots,
            "servicos_falhos": [{"servico": k, "ocorrencias": v}
                                for k, v in acc.servicos_falhos.most_common(40)],
            "redeploys_total": sum(acc.redeploys.values()),
            "redeploys_por_modulo": [{"modulo": k, "republicacoes": v}
                                     for k, v in acc.redeploys.most_common(20)],
            "redeploys_por_dia": [{"dia": k, "republicacoes": v}
                                  for k, v in sorted(acc.redeploys_por_dia.items())],
            "migracao_falhas_total": sum(acc.migracao_falhas.values()),
            "migracao_falhas_por_modulo": [{"modulo": k, "falhas": v}
                                           for k, v in acc.migracao_falhas.most_common(25)],
            "threads_nao_encerradas_total": sum(acc.threads_nao_encerradas.values()),
            "threads_nao_encerradas_por_dia": [{"dia": k, "falhas": v}
                                               for k, v in sorted(acc.threads_nao_encerradas.items())],
        },
    }


# ------------------------------------------------------------------- DML
def bloco_dml(fonte):
    """Estatisticas de DML por objeto (geradas pelo extratorDML da Sankhya).

    Formato de cada linha: OBJETO,TS_HORA_MS,OP,EXECUCOES,TEMPO_TOTAL_MS,LINHAS
    OP: 0=INSERT 1=UPDATE 2=DELETE 3=STP (procedure).
    """
    alvos = [n for n in fonte.nomes if "dml_stats/" in n and n.lower().endswith(".log")]
    if not alvos:
        return None

    ag = defaultdict(lambda: {"execucoes": 0, "tempo_ms": 0, "linhas": 0})
    por_dia = defaultdict(lambda: {"execucoes": 0, "tempo_ms": 0})
    por_hora = defaultdict(lambda: {"execucoes": 0, "tempo_ms": 0})
    descartadas = 0
    total_linhas = 0

    for n in alvos:
        with fonte.abrir(n) as f:
            for raw in io.TextIOWrapper(f, encoding=ENC, errors="replace"):
                partes = raw.strip().split(",")
                if len(partes) != 6:
                    continue
                total_linhas += 1
                obj, ts, op, ex, tp, ln = partes
                try:
                    ex, tp, ln, ts = int(ex), int(tp), int(ln), int(ts)
                except ValueError:
                    descartadas += 1
                    continue
                # Medida negativa e corrupcao do extrator, nao tempo real.
                if ex < 0 or tp < 0:
                    descartadas += 1
                    continue
                chave = (obj, OP_DML.get(op, op))
                a = ag[chave]
                a["execucoes"] += ex
                a["tempo_ms"] += tp
                a["linhas"] += ln
                try:
                    dt = datetime.fromtimestamp(ts / 1000.0)
                except (ValueError, OSError, OverflowError):
                    continue
                d = por_dia[dt.strftime("%Y-%m-%d")]
                d["execucoes"] += ex
                d["tempo_ms"] += tp
                h = por_hora[dt.strftime("%H")]
                h["execucoes"] += ex
                h["tempo_ms"] += tp

    objetos = []
    for (obj, op), a in ag.items():
        media = a["tempo_ms"] / a["execucoes"] if a["execucoes"] else 0
        limite = LIMITES_DML.get((obj, op))
        item = {
            "objeto": obj,
            "operacao": op,
            "execucoes": a["execucoes"],
            "tempo_total_ms": a["tempo_ms"],
            "tempo_medio_ms": round(media, 1),
            "linhas": a["linhas"],
            "limite_ms": limite,
            "personalizado": _parece_personalizado(obj),
        }
        if limite:
            item["excesso_pct"] = round((media / limite - 1) * 100, 1)
            item["acima_do_limite"] = media > limite * TOLERANCIA
        objetos.append(item)

    objetos.sort(key=lambda x: -x["tempo_total_ms"])
    return {
        "arquivos": len(alvos),
        "linhas": total_linhas,
        "linhas_descartadas": descartadas,
        "objetos": objetos[:120],
        "violacoes_limite": [o for o in objetos if o.get("acima_do_limite")],
        "por_dia": [{"dia": d, **v} for d, v in sorted(por_dia.items())],
        "por_hora_do_dia": [{"hora": h, **v} for h, v in sorted(por_hora.items())],
    }


# Procedures do produto. A lista precisa ser consultada ANTES da regra generica
# de STP_, senao uma procedure padrao cai no retorno final e e apontada como
# personalizacao — o que manda o cliente procurar "o autor da customizacao" de um
# objeto Sankhya.
P_PROC_PADRAO = re.compile(
    r"^STP_(SET_SESSION|CONFIRMANOTA|NUMERAR_NOTA|KEYGEN|CANCELANOTA|ESTORNANOTA|"
    r"GERA|CALC|ATUALIZA_EST|BAIXA|RATEIO|MONTA)", re.I)
P_PREFIXO_PADRAO = re.compile(
    r"^(TGF|TSI|TFP|TMD|TCS|TPR|TCB|TSE|TWM|TMS|TCT|TPA|EVT|TC_|V_TGF|V_TSI)", re.I)


def _agregar_hora_do_dia(acc):
    ent = Counter()
    err = Counter()
    for chave, v in acc.por_hora.items():
        ent[chave[11:13]] += v
    for chave, v in acc.erros_por_hora.items():
        err[chave[11:13]] += v
    return [{"hora": f"{h:02d}", "entradas": ent.get(f"{h:02d}", 0),
             "erros": err.get(f"{h:02d}", 0)} for h in range(24)]


def _parece_personalizado(obj):
    """Indicio de customizacao pela nomenclatura. Indicio, nao prova: o pacote de
    log nao lista objetos personalizados, e um nome pode enganar nos dois
    sentidos. Serve para ordenar a investigacao, nao para acusar."""
    if obj.upper().startswith("AD_"):
        return True
    if P_PROC_PADRAO.match(obj):
        return False
    if obj.upper().startswith("STP_"):
        return True
    if P_PREFIXO_PADRAO.match(obj):
        return False
    return True


# ------------------------------------------------------------ conexoes
def bloco_conexoes(fonte):
    """conn-stats/*.dat: registros de 20 bytes, big-endian, amostrados a cada 5 min.

    Layout: long timestamp_ms | int A | int B | int C.
    A e a serie que o sistema publica como conexoes; B e C vem zerados nos
    pacotes observados e ficam registrados sem rotulo ate confirmacao.
    """
    alvos = sorted(n for n in fonte.nomes if "conn-stats/" in n and n.lower().endswith(".dat"))
    if not alvos:
        return None

    serie = []
    for n in alvos:
        dados = fonte.ler(n)
        for i in range(0, len(dados) - 19, 20):
            ts, a, b, c = struct.unpack(">qiii", dados[i:i + 20])
            try:
                quando = datetime.fromtimestamp(ts / 1000.0)
            except (ValueError, OSError, OverflowError):
                continue
            serie.append({"quando": quando.strftime("%Y-%m-%d %H:%M"), "conexoes": a, "b": b, "c": c})

    if not serie:
        return None
    valores = [p["conexoes"] for p in serie]
    por_hora = defaultdict(list)
    for p in serie:
        por_hora[p["quando"][11:13]].append(p["conexoes"])
    pico = max(serie, key=lambda p: p["conexoes"])

    return {
        "arquivos": len(alvos),
        "amostras": len(serie),
        "intervalo_minutos": 5,
        "media": round(sum(valores) / len(valores), 1),
        "minimo": min(valores),
        "maximo": max(valores),
        "pico": pico,
        "p95": sorted(valores)[int(len(valores) * 0.95) - 1],
        "media_por_hora": [{"hora": h, "media": round(sum(v) / len(v), 1), "maximo": max(v)}
                           for h, v in sorted(por_hora.items())],
        "serie": serie,
    }


# -------------------------------------------------------------- threads
P_THREAD_CAB = re.compile(r'^"(.*)"\s+prio=(\d+)\s+tid=(\d+)\s+([A-Z_]+)\s*(\w+)?')
P_THREAD_MET = re.compile(r"native=(\w+), suspended=(\w+), block=(\d+), wait=(\d+)")
P_THREAD_LOCK = re.compile(r"lock=(\S+) owned by (\S+) \((-?\d+)\), cpu=(\d+), user=(\d+)")


# Familias de thread, na ordem em que sao testadas. O rotulo e funcional de
# proposito: o documento fala "varredura de deploy", nao "DeploymentScanner".
#
# Existe porque `top_cpu` sozinho engana. Ele mostra as 15 threads de maior CPU
# com a pilha crua, quase sempre parada em `Unsafe.park`, e o leitor conclui que
# nada consome CPU. Agregando por familia, um pacote real revelou 44,5% da CPU
# do processo em duas familias de infraestrutura contra 0,02% no atendimento de
# requisicao. Esse numero era o achado mais forte da analise, e saiu de
# agregacao feita a mao.
FAMILIAS_THREAD = [
    ("Cluster em memória",      (r"^hz\.", r"hazelcast", r"partition-operation", r"query-operation")),
    ("Varredura de deploy",     (r"^DeploymentScanner",)),
    ("Agendadores",             (r"Quartz", r"Scheduler_Worker", r"^AgentScheduler", r"^Timer")),
    ("Atendimento de requisição", (r"^default task",)),
    ("Entrada e saída de rede", (r"^default I/O", r"^XNIO", r"^Remoting")),
    ("Serviços do servidor",    (r"^MSC service", r"^ServerService", r"^Controller Boot")),
    ("Coleta de estatísticas",  (r"^SAS", r"MetricsRegistry")),
    ("Pools genéricos",         (r"^pool-\d", r"^ForkJoinPool")),
]


def _cpu_por_familia(threads):
    """Soma a CPU acumulada por familia de thread, do maior para o menor.

    `cpu_ms` do dump e tempo acumulado na vida de cada thread, nao taxa. Threads
    de requisicao sao curtas e morrem, entao a fatia delas e piso, nao medida
    exata. Ja as de infraestrutura sao singletons que vivem com o processo, e
    para essas o numero e solido. O JSON carrega o aviso junto.
    """
    if not threads:
        return None
    compilados = [(rot, [re.compile(p, re.I) for p in pats])
                  for rot, pats in FAMILIAS_THREAD]
    agr = defaultdict(lambda: {"cpu_ms": 0, "threads": 0})
    for t in threads:
        nome = t["nome"]
        rot = next((r for r, ps in compilados if any(p.search(nome) for p in ps)), "Outras")
        agr[rot]["cpu_ms"] += t["cpu_ms"]
        agr[rot]["threads"] += 1
    total = sum(v["cpu_ms"] for v in agr.values()) or 1
    saida = [{"familia": k, "cpu_ms": v["cpu_ms"], "threads": v["threads"],
              "pct_das_vivas": round(v["cpu_ms"] / total * 100, 2)}
             for k, v in agr.items()]
    saida.sort(key=lambda x: -x["cpu_ms"])
    return {
        "familias": saida,
        "ressalva": "cpu_ms e acumulado na vida de cada thread, nao taxa. Thread de "
                    "requisicao e curta e morre, entao a fatia dela e piso. Thread de "
                    "infraestrutura vive com o processo, e para essa o numero e solido. "
                    "O percentual sobre a CPU do processo sai de diagnostico.cpu_pct.",
    }


def bloco_threads(fonte):
    alvo = next((n for n in fonte.nomes if os.path.basename(n) == "threads.dump"), None)
    if not alvo:
        return None
    texto = fonte.texto(alvo)

    m = re.search(r"Dump das (\d+) thread.*?em ([\d/]+ [\d:]+)", texto)
    total_declarado = int(m.group(1)) if m else None
    gerado_em = m.group(2) if m else None

    threads = []
    for bloco in re.split(r"\n(?=\")", texto):
        cab = P_THREAD_CAB.match(bloco)
        if not cab:
            continue
        met = P_THREAD_MET.search(bloco)
        lock = P_THREAD_LOCK.search(bloco)
        pilha = [l.strip() for l in bloco.splitlines() if l.strip() and not l.strip().startswith(("native=", "lock="))][1:]
        threads.append({
            "nome": cab.group(1),
            "estado": cab.group(4),
            "tipo": cab.group(5),
            "block": int(met.group(3)) if met else 0,
            "wait": int(met.group(4)) if met else 0,
            "cpu_ms": int(lock.group(4)) if lock else 0,
            "user_ms": int(lock.group(5)) if lock else 0,
            "dono_lock": lock.group(2) if lock else None,
            "topo_pilha": pilha[0][:220] if pilha else None,
            "pilha": [p[:200] for p in pilha[:12]],
        })

    estados = Counter(t["estado"] for t in threads)
    grupos = Counter(re.sub(r"[-_]?\d+$", "", t["nome"]) for t in threads)
    bloqueadas = [t for t in threads if t["estado"] == "BLOCKED"]
    topo = Counter(t["topo_pilha"] for t in threads if t["topo_pilha"])
    familias = _cpu_por_familia(threads)

    return {
        "arquivo": alvo,
        "gerado_em": gerado_em,
        "total": total_declarado or len(threads),
        "analisadas": len(threads),
        "por_estado": dict(estados),
        "grupos": limitar(grupos, 20),
        "cpu_ms_total_vivas": sum(t["cpu_ms"] for t in threads),
        "cpu_por_familia": familias,
        "bloqueadas": [{"nome": t["nome"], "dono_lock": t["dono_lock"], "topo": t["topo_pilha"]} for t in bloqueadas[:25]],
        "top_cpu": sorted(threads, key=lambda t: -t["cpu_ms"])[:15],
        "top_block": sorted(threads, key=lambda t: -t["block"])[:15],
        "topos_de_pilha": limitar(topo, 15),
    }


# -------------------------------------------------------------- acessos
P_ALD_HORA = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),\d+ CBL")
P_ALD_ACM = re.compile(r"\[CB-ACM\] CODUSU: (\d+) SEQACESSO: (\d+) DHACESSO: ([\d\-: .]+) RESOURCEID: (\S+)(?: CAMINHO: (.*?))?(?: DESCRMENU: (.*))?$")
P_ALD_RLG = re.compile(r"\[CB-RLG\] user: (.*?) accountUser:")
P_ALD_URL = re.compile(r"\|URL: (\S+)(?: (.*))?$")
P_ALD_IP = re.compile(r"\|IP: (\S+)")
P_ALD_SESSAO = re.compile(r"sessionId: (\S+)")


def bloco_acessos(fonte):
    """.ald/cb-AAAA-MM-DD.log: trilha de acesso por usuario, tela e IP."""
    alvos = sorted(n for n in fonte.nomes if "/.ald/" in "/" + n and n.lower().endswith(".log"))
    if not alvos:
        return None

    telas = Counter()
    usuarios = Counter()
    ips = Counter()
    servicos = Counter()
    por_hora = Counter()
    por_dia = Counter()
    sessoes = set()
    sessoes_por_dia = defaultdict(set)

    for n in alvos:
        m_dia = P_DATA_NOME.search(os.path.basename(n))
        dia = m_dia.group(0) if m_dia else "?"
        with fonte.abrir(n) as f:
            for raw in io.TextIOWrapper(f, encoding=ENC, errors="replace"):
                linha = raw.rstrip("\n")
                mh = P_ALD_HORA.match(linha)
                if mh:
                    por_hora[mh.group(1)] += 1
                    por_dia[dia] += 1
                    continue
                m = P_ALD_ACM.search(linha)
                if m:
                    tela = (m.group(6) or m.group(4) or "").strip()
                    if tela:
                        telas[tela] += 1
                    usuarios[m.group(1)] += 1
                    continue
                m = P_ALD_RLG.search(linha)
                if m:
                    usuarios[m.group(1).strip().upper()] += 1
                m = P_ALD_IP.search(linha)
                if m:
                    ips[m.group(1)] += 1
                m = P_ALD_URL.search(linha)
                if m and m.group(2) and "serviceName=" in m.group(2):
                    sv = re.search(r"serviceName=([\w.$]+)", m.group(2))
                    if sv:
                        servicos[sv.group(1)] += 1
                m = P_ALD_SESSAO.search(linha)
                if m and m.group(1) != "null":
                    sessoes.add(m.group(1))
                    sessoes_por_dia[dia].add(m.group(1))

    return {
        "arquivos": len(alvos),
        "dias": len(por_dia),
        "eventos": sum(por_dia.values()),
        "sessoes_distintas": len(sessoes),
        "sessoes_por_dia": [{"dia": d, "sessoes": len(s)} for d, s in sorted(sessoes_por_dia.items())],
        "eventos_por_hora": [{"hora": h, "eventos": v} for h, v in sorted(por_hora.items())],
        "eventos_por_dia": [{"dia": d, "eventos": v} for d, v in sorted(por_dia.items())],
        "top_telas": limitar(telas, 25),
        "top_usuarios": limitar(usuarios, 25),
        "top_ips": limitar(ips, 15),
        "top_servicos": limitar(servicos, 20),
    }


# ------------------------------------------------------------- licencas
def bloco_licencas(fonte):
    alvos = [n for n in fonte.nomes if n.startswith("sas-server/") and n.lower().endswith(".log")]
    if not alvos:
        return None
    alvo = max(alvos, key=lambda n: fonte.tamanho(n))
    texto = fonte.texto(alvo, 400000)
    modulos = {}
    atual = None
    for linha in texto.splitlines():
        m = re.search(r"License for (\d+) :(.+)$", linha)
        if m:
            atual = m.group(2).strip()
            modulos.setdefault(atual, {"codigo": m.group(1)})
            continue
        m = re.search(r"Total licenses to (\d+) :(\d+)", linha)
        if m and atual:
            modulos[atual]["quantidade"] = int(m.group(2))
            atual = None
    versao = re.search(r"Vers[^:]*o do SAS: (\S+)", texto)
    return {
        "arquivo": alvo,
        "versao_sas": versao.group(1) if versao else None,
        "modulos": [{"modulo": k, **v} for k, v in sorted(modulos.items())],
        "total_modulos": len(modulos),
    }


# ------------------------------------------------------------ banco/dialeto
# Reconhecimento do banco em uso. Existe porque toda recomendacao que termina
# em script depende do dialeto, e o pacote traz QUATRO fontes que podem
# discordar. A lista de drivers carregados e a pior delas: um ambiente Oracle
# com o driver de SQL Server no deploy e comum, e decidir por ela entrega ao
# cliente o script do banco errado.
#
# Ordem de precedencia, da mais forte para a mais fraca:
#   1. URL do datasource em mge-ds.xml  -> e o que a aplicacao efetivamente usa
#   2. banner do banco no server.log    -> so existe quando o driver o registra
#   3. classe do driver do datasource   -> aponta o modulo, nao a conexao
#   4. driver carregado, se houver um so -> ultimo recurso
DIALETOS = {
    "oracle": {
        "nome": "Oracle Database",
        "urls": ("jdbc:oracle:", "jdbc:oci:"),
        "drivers": ("oracle.jdbc", "com.oracle", "ojdbc"),
        "banner": "oracle database",
    },
    "sqlserver": {
        "nome": "Microsoft SQL Server",
        "urls": ("jdbc:sqlserver:", "jdbc:jtds:sqlserver:", "jdbc:microsoft:"),
        "drivers": ("com.microsoft.sqlserver", "net.sourceforge.jtds",
                    "mssql-jdbc", "jtds"),
        "banner": "microsoft sql server",
    },
}

# Driver interno do proprio servidor de aplicacoes. Nunca e o banco do cliente.
DRIVER_INTERNO = ("org.h2.driver",)

CATALOGO_SQL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "references", "scripts-sql", "catalogo.json")


def _dialeto_por(valor, chave):
    """Casa um valor contra os padroes de `chave` ('urls', 'drivers', 'banner')."""
    if not valor:
        return None
    v = valor.strip().lower()
    for dialeto, regra in DIALETOS.items():
        padroes = regra[chave]
        padroes = (padroes,) if isinstance(padroes, str) else padroes
        if any(pad in v for pad in padroes):
            return dialeto
    return None


def _scripts_do_dialeto(dialeto):
    """Le o catalogo e devolve os scripts aplicaveis ao dialeto detectado.

    Item sem arquivo para o dialeto entra como lacuna, nunca omitido: omitir
    faz o analista supor que a verificacao nao existe.
    """
    try:
        with open(CATALOGO_SQL, encoding="utf-8") as f:
            cat = json.load(f)
    except (OSError, ValueError) as e:
        return {"erro": f"catalogo de scripts nao lido: {type(e).__name__}: {e}"}

    aplicaveis, lacunas = [], []
    for item in cat.get("itens", []):
        arquivos = item.get("arquivos") or {}
        arquivo = arquivos.get(dialeto) if dialeto else None
        base = {
            "id": item.get("id"),
            "pergunta": item.get("pergunta"),
            "responde": item.get("responde"),
            "tipo": item.get("tipo"),
        }
        if arquivo:
            base["arquivo"] = arquivo
            base["origem"] = (item.get("origem") or {}).get(dialeto)
            dep = (item.get("dependencia") or {}).get(dialeto)
            if dep:
                base["dependencia"] = dep
            aplicaveis.append(base)
        else:
            base["motivo"] = item.get("lacuna") or (
                "Sem script para este dialeto no acervo da skill."
                if dialeto else "Dialeto do banco nao identificado no pacote.")
            lacunas.append(base)
    return {"aplicaveis": aplicaveis, "lacunas": lacunas}


def bloco_banco(ev):
    """Identifica o banco em uso e lista os scripts aplicaveis a ele.

    Depende de `ambiente` e `logs` ja coletados. Quando as fontes discordam, o
    campo `conflito` guarda as duas leituras: o documento tem de dizer que
    discordam em vez de escolher uma em silencio.
    """
    amb = ev.get("ambiente") or {}
    logs = ev.get("logs") or {}
    ds = amb.get("datasource") or {}

    url = ds.get("url")
    driver_ds = ds.get("driver")
    banners = logs.get("banco") or []
    banner = banners[0]["banner"] if banners else None

    por_url = _dialeto_por(url, "urls")
    por_banner = _dialeto_por(banner, "banner")
    por_driver_ds = _dialeto_por(driver_ds, "drivers")

    carregados = []
    for d in logs.get("drivers_carregados", []):
        classe = (d.get("classe") or "")
        if classe.lower() in DRIVER_INTERNO:
            continue
        dial = _dialeto_por(classe, "drivers")
        if dial:
            carregados.append((dial, classe))
    dialetos_carregados = sorted({d for d, _ in carregados})
    por_carregado = dialetos_carregados[0] if len(dialetos_carregados) == 1 else None

    if por_url:
        dialeto, fonte = por_url, "URL do datasource em mge-ds.xml"
        evidencia = _url_sem_credencial(url)
    elif por_banner:
        dialeto, fonte, evidencia = por_banner, "banner do banco no server.log", banner
    elif por_driver_ds:
        dialeto, fonte, evidencia = por_driver_ds, "classe do driver do datasource", driver_ds
    elif por_carregado:
        dialeto = por_carregado
        fonte = "unico driver de banco carregado no deploy"
        evidencia = carregados[0][1]
    else:
        dialeto, fonte, evidencia = None, None, None

    conflito = None
    if por_url and por_banner and por_url != por_banner:
        conflito = {
            "url": {"dialeto": por_url, "evidencia": _url_sem_credencial(url)},
            "banner": {"dialeto": por_banner, "evidencia": banner},
            "leitura": "A URL do datasource prevalece: e a conexao que a aplicacao "
                       "abre. Banner divergente costuma vir de outro datasource "
                       "no mesmo servidor. Conferir antes de entregar script.",
        }

    return {
        "dialeto": dialeto,
        "nome": DIALETOS[dialeto]["nome"] if dialeto else None,
        "fonte": fonte,
        "evidencia": evidencia,
        "banner": banner,
        "versao": _versao_do_banner(banner),
        "conflito": conflito,
        "drivers_carregados": dialetos_carregados,
        "scripts": _scripts_do_dialeto(dialeto),
    }


def _url_sem_credencial(url):
    """Encurta a URL do datasource: host, porta e SID nao vao para o documento."""
    if not url:
        return None
    for dialeto, regra in DIALETOS.items():
        for pref in regra["urls"]:
            if url.strip().lower().startswith(pref):
                return pref + "..."
    return url.split("@")[0] + "..." if "@" in url else url


def _versao_do_banner(banner):
    """Extrai a versao numerica do banner. Sem banner, nao ha versao: nunca
    inferir a versao do banco a partir da versao do driver."""
    if not banner:
        return None
    m = re.search(r"(\d+\.\d+(?:\.\d+)*)", banner)
    return m.group(1) if m else None


# ------------------------------------------------------- wildfly/baseline
# Versao do pacote de referencia distribuido pela Sankhya, em
# references/baseline-wildfly23/. Trocar os arquivos de la atualiza a
# comparacao sem mexer neste codigo.
BASELINE_VERSAO = "23.0"
BASELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "references", "baseline-wildfly23")

# Drivers empacotados no baseline, com a versao lida do manifesto de cada JAR.
DRIVERS_BASELINE = {
    "oracle.jdbc.OracleDriver": "19.26.0.0.0",
    "oracle.jdbc.driver.OracleDriver": "19.26.0.0.0",
    "com.microsoft.sqlserver.jdbc.SQLServerDriver": "4.1",
    "net.sourceforge.jtds.jdbc.Driver": "1.3.1",
    "com.mysql.jdbc.Driver": "8.0.30",
    "com.mysql.cj.jdbc.Driver": "8.0.30",
}

# Argumentos cujo valor e proprio do ambiente: divergir do baseline e o
# esperado, nao um desvio. Comparar estes gera ruido e desacredita a lista.
ARGS_DO_AMBIENTE = {
    "jboss.socket.binding.port-offset", "jboss.bind.address",
    "jboss.bind.address.management", "jboss.node.name", "jboss.server.log.dir",
    "jboss.server.base.dir", "jboss.server.config.dir", "java.io.tmpdir",
    "snk.auth.folder", "skw.cluster.nodes", "skw.cluster.pref.run.job",
    "javax.net.ssl.trustStore", "javax.net.ssl.keyStore",
    "javax.net.ssl.trustStorePassword", "javax.net.ssl.keyStorePassword",
    "sankhyaw.only.jobs", "jboss.modules.system.pkgs",
    # injetados pelo proprio script de inicializacao, nao escolhidos por ninguem
    "logging.configuration", "org.jboss.boot.log.file", "program.name",
    "jboss.home.dir", "java.security.egd", "user.timezone",
}

# Memoria e dimensionamento. O baseline traz 1024/2048 como ponto de partida da
# instalacao, nao como valor recomendado para todo porte: um cliente com mais
# usuarios deve ter mais. Reportar como "divergente do recomendado" seria
# errado. Vao para uma lista propria, com a leitura correta no documento.
ARGS_DIMENSIONAMENTO = {"-Xms", "-Xmx", "-Xss", "XX:MaxMetaspaceSize",
                        "XX:MaxDirectMemorySize"}

# Argumentos do baseline que dependem do banco ou do sistema operacional.
# Ausencia aqui costuma ser correta, e afirmar o contrario queima a lista toda.
ARGS_CONDICIONAIS = {
    "jape.sqlserver.use.native.query.getpk": "aplica-se a SQL Server",
    "jape.mysql.lowercase": "aplica-se a MySQL",
    "xnio.nio.selector.main": "presente no standalone.conf de Linux",
    "xnio.nio.selector.temp": "presente no standalone.conf de Linux",
    "xnio.nio.selector.provider": "presente no standalone.conf de Linux",
    "java.nio.channels.spi.SelectorProvider": "presente no standalone.conf de Linux",
    "-XX:+UnlockExperimentalVMOptions": "acompanha o G1 no standalone.conf de Linux",
}

P_ARG = re.compile(r"(-D[\w.\-]+=[^\s\"]*|-XX:[+\-]?[\w:=.]+|-X(?:ms|mx|ss)[\w]+)")


def _args_do_baseline():
    """Le os argumentos do standalone.conf/.bat de referencia."""
    args = {}
    for nome in ("standalone.conf", "standalone.conf.bat"):
        caminho = os.path.join(BASELINE_DIR, nome)
        if not os.path.exists(caminho):
            continue
        with open(caminho, encoding=ENC, errors="replace") as f:
            texto = f.read()
        # linhas comentadas nao valem como referencia
        ativas = [l for l in texto.splitlines()
                  if not l.strip().startswith(("#", "rem ", "REM ", "rem#"))]
        for a in P_ARG.findall("\n".join(ativas)):
            k, v = _quebrar_arg(a)
            args.setdefault(k, v)
    return args


def _quebrar_arg(a):
    if a.startswith("-D") and "=" in a:
        k, v = a[2:].split("=", 1)
        return k, v
    if a.startswith(("-Xms", "-Xmx", "-Xss")):
        return a[:4], a[4:]
    return a, None


def bloco_wildfly(ev):
    """Compara o ambiente do cliente com o pacote WildFly de referencia.

    Nao decide sozinho o que e problema: separa ausente, divergente e extra, e
    deixa a leitura para o analista. Argumento proprio do ambiente (porta, IP,
    caminho) fica de fora da comparacao.
    """
    amb = ev.get("ambiente") or {}
    logs = ev.get("logs") or {}
    base = _args_do_baseline()
    if not base:
        return {"erro": "baseline nao encontrado em references/baseline-wildfly23/"}

    cliente = {}
    for a in amb.get("vm_args", []):
        k, v = _quebrar_arg(a.strip())
        cliente[k] = v

    ausentes, condicionais, divergentes, dimensionamento, extras = [], [], [], [], []
    for k, v in sorted(base.items()):
        if k in ARGS_DO_AMBIENTE:
            continue
        if k in ARGS_DIMENSIONAMENTO:
            if k in cliente and cliente[k] != v:
                dimensionamento.append({"argumento": k, "valor_cliente": cliente[k],
                                        "valor_referencia": v})
            continue
        if k not in cliente:
            item = {"argumento": k, "valor_referencia": v}
            if k in ARGS_CONDICIONAIS:
                item["motivo"] = ARGS_CONDICIONAIS[k]
                condicionais.append(item)
            else:
                ausentes.append(item)
        elif v is not None and cliente[k] != v:
            divergentes.append({"argumento": k, "valor_cliente": cliente[k], "valor_referencia": v})
    for k, v in sorted(cliente.items()):
        if k not in base and k not in ARGS_DO_AMBIENTE and k not in ARGS_DIMENSIONAMENTO:
            extras.append({"argumento": k, "valor_cliente": v})

    # versao do servidor de aplicacoes
    versao = (amb.get("versao_servidor") or "").strip()
    m = re.match(r"(\d+)", versao)
    major = int(m.group(1)) if m else None
    base_major = int(BASELINE_VERSAO.split(".")[0])

    drivers = []
    for d in logs.get("drivers_carregados", []):
        ref = DRIVERS_BASELINE.get(d["classe"])
        item = {"classe": d["classe"], "versao_cliente": d["versao"], "versao_referencia": ref}
        item["atrasado"] = bool(ref and _versao_menor(d["versao"], ref))
        item["descontinuado"] = "jtds" in d["classe"].lower()
        drivers.append(item)

    return {
        "baseline": {
            "versao": BASELINE_VERSAO,
            "pacote": "Wildfly_23.0_Sankhya_mod_05",
            "arquivos": sorted(os.path.basename(p) for p in
                               (os.path.join(BASELINE_DIR, n) for n in os.listdir(BASELINE_DIR))),
        },
        "versao_cliente": versao or None,
        "major_cliente": major,
        "major_baseline": base_major,
        "desatualizado": bool(major and major < base_major),
        "argumentos_cliente": [{"argumento": k, "valor": v} for k, v in sorted(cliente.items())],
        "ausentes": ausentes,
        "ausentes_condicionais": condicionais,
        "divergentes": divergentes,
        "dimensionamento": dimensionamento,
        "extras": extras,
        "drivers": drivers,
        "drivers_invalidos": logs.get("drivers_invalidos", []),
        "banco": logs.get("banco", []),
    }


def _versao_menor(a, b):
    """Compara versoes por segmento numerico. '19.23' < '19.26.0.0.0'."""
    def partes(v):
        return [int(x) for x in re.findall(r"\d+", v)]
    pa, pb = partes(a), partes(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa < pb


# --------------------------------------------------------------- achados
def gerar_achados(ev):
    """Regras objetivas. Cada achado carrega o numero que o sustenta.

    Nao interpreta e nao prioriza negocio: isso e trabalho do analista sobre
    o JSON. Aqui so entra o que um limiar consegue decidir sozinho.
    """
    achados = []

    def add(chave, titulo, severidade, evidencia, fonte, recomendacao):
        achados.append({
            "chave": chave, "titulo": titulo, "severidade": severidade,
            "evidencia": evidencia, "fonte": fonte, "recomendacao": recomendacao,
        })

    amb = ev.get("ambiente", {})
    # --- memoria e JVM
    xms, xmx = amb.get("xms_mb"), amb.get("xmx_mb")
    if xms and xmx and xms != xmx:
        add("heap_desbalanceado",
            "Heap minima e maxima com valores diferentes",
            "media",
            f"-Xms{xms}m e -Xmx{xmx}m.",
            "Argumentos da VM",
            "Igualar Xms e Xmx. O checklist da Sankhya pede o mesmo valor: heap que cresce "
            "em tempo de execucao provoca pausa de coleta no momento de maior uso.")
    # `Memoria Heap: usado / total` do cabecalho NAO e uso real quando Xms = Xmx:
    # a maquina virtual reserva a heap inteira na subida, e a razao da 100% em
    # todo pacote com essa configuracao, que e justamente a recomendada pelo
    # checklist. Num pacote real isso virou "heap a 100%, severidade alta" com o
    # GC gastando 0,09% do tempo. Dois guardas, nesta ordem:
    #   1. Xms = Xmx invalida a leitura na origem;
    #   2. tempo em GC dentro do recomendado desmente pressao de memoria.
    uso = amb.get("heap_uso_pct")
    diag = ev.get("diagnostico") or {}
    gc_pct = diag.get("gc_pct")
    heap_reservada = bool(xms and xmx and xms == xmx)
    gc_tranquilo = gc_pct is not None and gc_pct < 2
    if uso is not None and uso >= 85 and not heap_reservada and not gc_tranquilo:
        add("heap_pressionada",
            "Heap perto do limite no momento da coleta",
            "alta" if uso >= 92 else "media",
            f"{amb.get('heap_usado_mb')} MB de {amb.get('heap_total_mb')} MB ({uso}%).",
            "Cabecalho do pacote de log",
            "Heap nessa faixa faz o coletor rodar em ciclo continuo e a aplicacao congela "
            "durante as pausas. Avaliar aumento de heap e investigar retencao de objetos.")

    # O contrario tambem e achado, e mais confiavel: o tempo em GC vem medido.
    if gc_pct is not None and gc_pct >= 2:
        add("gc_custoso",
            "Tempo em coleta de lixo acima do recomendado",
            "alta" if gc_pct >= 5 else "media",
            f"{gc_pct}% do tempo de CPU do processo, contra o maximo de 2% recomendado "
            f"pelo proprio diagnostico do pacote.",
            "Bloco de diagnostico do pacote",
            "Pausa de coleta nessa faixa e sentida como travamento. Habilitar o registro "
            "de coleta de lixo e recoletar para medir a duracao de cada pausa.")

    if diag.get("cache_codigo_mb") == 0:
        add("cache_codigo_zerado",
            "Cache de codigo sem dimensionamento",
            "media",
            "Memoria do espaco de codigo em 0, contra o minimo de 256 MB recomendado "
            "pelo proprio diagnostico do pacote.",
            "Bloco de diagnostico do pacote",
            "Cache cheio faz a maquina virtual descartar codigo ja compilado e voltar a "
            "interpretar. Incluir -XX:ReservedCodeCacheSize=256m nos argumentos.")

    if diag.get("triggers_pendentes"):
        add("triggers_desabilitadas",
            "Triggers desabilitadas pendentes na base",
            "media",
            "O diagnostico do pacote aponta pendencia na tabela de controle de triggers.",
            "Bloco de diagnostico do pacote",
            "Trigger desabilitada e nao reabilitada deixa de aplicar a regra que carrega. "
            "Risco de integridade, nao de desempenho. Acionar o DBA do cliente.")

    if diag.get("producao") is False:
        add("pacote_nao_producao",
            "Pacote coletado fora do ambiente de producao",
            "alta",
            f"Estereotipo da base: {diag.get('estereotipo')}.",
            "Registro de base no cabecalho do pacote",
            "Lentidao relatada em producao nao e mensuravel neste pacote. Confirmar com o "
            "cliente qual instancia apresenta o sintoma e recoletar na correta.")
    gc = amb.get("gc")
    if gc and "ConcMarkSweep" in gc:
        add("gc_cms",
            "Coletor CMS em uso",
            "baixa",
            f"Argumento {gc}.",
            "Argumentos da VM",
            "CMS foi descontinuado a partir do Java 9 e sofre com fragmentacao em heap grande. "
            "G1 (-XX:+UseG1GC) e o coletor indicado no material de argumentos da Sankhya.")
    java = amb.get("java", "")
    if "1.8" in java:
        add("java8",
            "Java 8 em producao",
            "baixa",
            java,
            "Cabecalho do pacote de log",
            "Versao suportada pelo WildFly padrao Sankhya, mas sem os coletores modernos. "
            "Registrar como restricao ao recomendar ajuste de GC.")
    args = amb.get("vm_args_map", {})
    if not any(a.startswith("-XX:+HeapDumpOnOutOfMemoryError") for a in amb.get("vm_args", [])):
        add("sem_heapdump",
            "Sem geracao automatica de heap dump",
            "baixa",
            "Argumento -XX:+HeapDumpOnOutOfMemoryError ausente.",
            "Argumentos da VM",
            "Sem o dump, um estouro de memoria nao deixa evidencia analisavel e a proxima "
            "ocorrencia exige reproduzir o problema.")
    if args.get("sankhyaw.schedule.disable") == "true":
        add("jobs_desligados",
            "Execucao de JOBs desabilitada no servidor",
            "alta",
            "-Dsankhyaw.schedule.disable=true",
            "Argumentos da VM",
            "Nenhum JOB roda nesta instancia. Confirmar se e intencional (no de cluster sem jobs).")
    if "sankhyaw.only.jobs" in args:
        add("jobs_restritos",
            "Execucao de JOBs restrita a uma lista",
            "media",
            f"-Dsankhyaw.only.jobs={args['sankhyaw.only.jobs']}",
            "Argumentos da VM",
            "Somente os JOBs listados executam. Verificar se rotinas de negocio ficaram de fora.")

    # --- DML
    dml = ev.get("dml") or {}
    for o in dml.get("violacoes_limite", []):
        sev = "alta" if o["excesso_pct"] >= 100 else "media"
        add("dml_acima_limite",
            f"{o['objeto']} {o['operacao']} acima do tempo de referencia",
            sev,
            f"Media de {o['tempo_medio_ms']} ms em {o['execucoes']} execucoes; "
            f"referencia {o['limite_ms']} ms ({o['excesso_pct']:+.0f}%).",
            "dml_stats",
            "O checklist da Sankhya atribui excesso nesses objetos a triggers, eventos e "
            "demais personalizacoes sobre a tabela. Levantar os objetos personalizados que "
            "atuam nela antes de tratar como problema de infraestrutura.")
    for o in dml.get("objetos", [])[:40]:
        if o.get("limite_ms"):
            continue
        if o["tempo_medio_ms"] >= CORTE_MEDIA_MS and o["tempo_total_ms"] >= CORTE_TEMPO_TOTAL_MS:
            add("dml_objeto_lento",
                f"{o['objeto']} com tempo medio alto",
                "alta" if o["tempo_medio_ms"] >= 5000 else "media",
                f"Media de {o['tempo_medio_ms']} ms em {o['execucoes']} execucoes "
                f"({o['tempo_total_ms']} ms no periodo).",
                "dml_stats",
                "Objeto personalizado" if o["personalizado"] else "Objeto padrao",
                )

    # --- conexoes
    conn = ev.get("conexoes") or {}
    ds = amb.get("datasource") or {}
    try:
        maxpool = int(ds.get("max_pool")) if ds.get("max_pool") else None
    except (TypeError, ValueError):
        maxpool = None
    # A espera por conexao livre e o que decide se ha disputa pelo pool. Pico
    # alto com espera de milissegundos nao e gargalo, e sem essa frase o achado
    # de ocupacao vira recomendacao de aumentar pool que nao muda nada.
    espera = (ev.get("diagnostico") or {}).get("espera_conexao_ms_media")
    ressalva_espera = (
        f" A espera media por conexao livre ficou em {espera:.0f} ms, contra o limiar "
        f"de 1000 ms: nao ha disputa medida pelo pool."
        if espera is not None and espera < 1000 else "")

    if conn and maxpool:
        ocupacao = conn["maximo"] / maxpool * 100
        if ocupacao > 105:
            # A serie excede o pool configurado: ela nao mede apenas esse datasource.
            # Reportar como inconsistencia a verificar, nunca como "pool a 175%".
            add("conexoes_acima_do_pool",
                "Serie de conexoes acima do pool configurado",
                "media",
                f"Pico de {conn['maximo']} contra max-pool-size de {maxpool} no datasource "
                f"principal. A serie nao e atribuivel apenas a esse pool." + ressalva_espera,
                "conn-stats + mge-ds.xml",
                "Verificar se ha outras instancias (TESTE/TREINA) ou outros datasources no "
                "mesmo servidor antes de concluir sobre dimensionamento. O checklist pede "
                "que instancias sem uso estejam paradas.")
        elif ocupacao >= 80:
            add("pool_saturado",
                "Pool de conexoes perto do limite",
                "alta" if ocupacao >= 95 else "media",
                f"Pico de {conn['maximo']} conexoes contra max-pool-size de {maxpool} "
                f"({ocupacao:.0f}%)." + ressalva_espera,
                "conn-stats + mge-ds.xml",
                "Pool no teto faz requisicao esperar por conexao livre, o que o usuario "
                "percebe como lentidao geral sem erro no log.")

    # --- logs
    logs = ev.get("logs") or {}
    sinais = logs.get("sinais", {})
    mapa_sinal = {
        "oom_heap": ("Estouro de memoria heap", "critica",
                     "OutOfMemoryError encerra threads em estado indefinido. Trata-se de "
                     "indisponibilidade, nao de lentidao."),
        "gc_overhead": ("Coletor de lixo sem progresso", "critica",
                        "A JVM passou mais tempo coletando do que executando. Heap insuficiente "
                        "ou retencao de objetos."),
        "pool_exausto": ("Pool de conexoes esgotado", "critica",
                         "Requisicao sem conexao disponivel falha ou espera. Efeito imediato no usuario."),
        "datapager_lento": ("Paginas de dados geradas e nao consumidas", "alta",
                            "Consulta que devolve volume grande e o cliente nao consome no prazo. "
                            "Indica tela sem filtro adequado ou rede saturada."),
        "timeout_query": ("Timeout de consulta", "alta",
                          "Consulta ultrapassou jape.global.query.timeout. Verificar plano de execucao."),
        "timeout_txn": ("Timeout de transacao", "alta",
                        "Somatorio das consultas da rotina excede o limite, mesmo com cada uma rapida."),
        "deadlock_java": ("Deadlock relatado", "alta",
                          "Contencao entre threads ou sessoes de banco."),
        "timeout_socket": ("Timeout de socket", "media",
                           "Chamada externa sem resposta: integracao, SEFAZ ou servico de e-mail."),
        "epoll_hang": ("Trava de epoll detectada", "media",
                       "Sintoma conhecido de IO em WildFly sob carga."),
        "deploy_timeout": ("Timeout durante o deploy", "media",
                           "WFLYCTL0348: servidor sobrecarregado na subida."),
        "conexao_fechada": ("Uso de conexao ja fechada", "media",
                            "Conexao devolvida ao pool e reutilizada apos o fechamento pelo banco."),
    }
    for chave, (titulo, sev, texto) in mapa_sinal.items():
        n = sinais.get(chave, 0)
        if n:
            add("sinal_" + chave, titulo, sev,
                f"{n} ocorrencia(s) no periodo analisado.",
                "server.log / stdout", texto)

    for o in (logs.get("oracle") or [])[:10]:
        if o["codigo"] in ("ORA-00060", "ORA-01013", "ORA-04031", "ORA-12516", "ORA-00257", "ORA-01555"):
            add("oracle_" + o["codigo"],
                f"{o['codigo']} no log",
                "alta",
                f"{o['ocorrencias']} ocorrencia(s). {o.get('significado') or ''}".strip(),
                "server.log / stdout",
                "Codigo com leitura direta de performance no checklist da Sankhya. "
                "Encaminhar ao DBA com o trecho de log.")

    total = logs.get("total_eventos") or 1
    erros = logs.get("total_eventos_erro", 0)
    taxa = erros / total * 100
    if taxa >= 5:
        add("taxa_erro",
            "Proporcao alta de eventos de erro",
            "alta" if taxa >= 15 else "media",
            f"{erros} eventos de erro em {total} eventos ({taxa:.1f}%). "
            f"As {logs.get('linhas_stacktrace', 0)} linhas de continuacao de stacktrace "
            f"ficaram de fora da conta.",
            "server.log / stdout",
            "Log com erro em volume alto esconde o evento relevante e custa IO de disco no "
            "mesmo servidor da aplicacao. Tratar as assinaturas do topo do ranking reduz o ruido.")

    # --- servidor de aplicacoes e drivers
    wf = ev.get("wildfly") or {}
    if wf.get("desatualizado"):
        add("wildfly_desatualizado",
            f"Servidor de aplicações na versão {wf['versao_cliente']}",
            "media",
            f"WildFly {wf['versao_cliente']} contra {wf['baseline']['versao']} do pacote "
            f"de referência da Sankhya ({wf['baseline']['pacote']}).",
            "Cabecalho do pacote de log e pacote de referencia",
            "O pacote de referencia ja vem com G1, drivers atualizados e os argumentos "
            "de JAPE consolidados. A troca e substituicao de instalacao, com migracao de "
            "configuracao e dos modulos personalizados, e pede janela e plano de retorno.")

    if wf.get("ausentes"):
        criticos = [a for a in wf["ausentes"]
                    if a["argumento"] in ("XX:+UseG1GC", "file.encoding",
                                          "java.util.Arrays.useLegacyMergeSort",
                                          "jape.experimental.commit-type")]
        add("args_ausentes",
            "Argumentos do pacote de referência ausentes na configuração",
            "media" if criticos else "baixa",
            f"{len(wf['ausentes'])} argumento(s) do standalone.conf de referência não "
            f"constam nos argumentos da VM do cliente.",
            "Argumentos da VM x baseline",
            "Avaliar item a item. Nem toda ausencia e desvio: parte dos argumentos do "
            "pacote de referencia trata banco ou sistema operacional que o cliente nao usa.")

    for d in wf.get("drivers", []):
        if d.get("descontinuado"):
            add("driver_jtds",
                "Driver jTDS carregado",
                "media",
                f"{d['classe']} versão {d['versao_cliente']}.",
                "Log de deploy do WildFly",
                "O jTDS e projeto de terceiros sem manutencao desde 2013 e nao acompanha "
                "os recursos do SQL Server atual. Para SQL Server, usar o driver oficial "
                "da Microsoft (mssql-jdbc), na versao compativel com a do banco.")
        elif d.get("atrasado"):
            add("driver_atrasado",
                f"Driver {d['classe'].split('.')[-1]} atrás da versão de referência",
                "baixa",
                f"Versão {d['versao_cliente']} contra {d['versao_referencia']} do pacote de referência.",
                "Log de deploy do WildFly",
                "Atualizar o JAR do modulo correspondente. Driver e o componente de menor "
                "risco de atualizacao no ambiente, e correcoes de desempenho e de vazamento "
                "de cursor costumam vir nele.")

    # O H2 e do proprio WildFly e nao conta como driver a mais.
    externos = [d for d in wf.get("drivers", []) if "h2" not in d["classe"].lower()]
    if len(externos) > 1:
        classes = ", ".join(d["classe"].split(".")[-1] for d in externos)
        add("drivers_demais",
            "Mais de um driver de banco carregado",
            "baixa",
            f"{len(externos)} drivers além do H2 interno: {classes}.",
            "Log de deploy do WildFly",
            "O datasource usa um so. Cada driver a mais ocupa memoria e tempo na subida. "
            "Manter apenas o do banco em uso.")

    # Um unico achado agregado. Estas mensagens vem do manifesto de JARs dentro
    # do EAR e nao sao, em regra, modulo de driver quebrado: sao referencia de
    # Class-Path a um arquivo que nao esta no pacote. Emitir um achado por JAR
    # produzia seis entradas de severidade media para um aviso de empacotamento.
    invalidos = wf.get("drivers_invalidos") or []
    if invalidos:
        lista = ", ".join(f"{d['jar']} ({d['ocorrencias']}x)" for d in invalidos[:6])
        add("classpath_nao_resolvido",
            "Referências de Class-Path não resolvidas no deploy",
            "baixa",
            f"{len(invalidos)} arquivo(s) referenciados e não encontrados: {lista}.",
            "Log de inicializacao do WildFly",
            "Aviso de empacotamento: o manifesto de um componente aponta para um arquivo "
            "que nao esta no pacote. Sem efeito em execucao quando o componente nao e "
            "usado. Vale conferir os que pertencem a personalizacao, porque costumam "
            "indicar entrega incompleta.")

    # --- ciclo de vida do servidor
    # Os quatro achados abaixo foram, numa analise real, escavados a mao no zip:
    # cada um custou uma chamada com script proprio. Sao os mais fortes que o
    # pacote sustenta, e nenhum depende de volume de usuario.
    ciclo = logs.get("ciclo_de_vida") or {}

    boots = ciclo.get("boots") or []
    lento = [b for b in boots if b.get("tempo_ms", 0) >= 120000]
    com_erro = [b for b in boots if b.get("com_erros")]
    if lento or com_erro:
        tempos = ", ".join(f"{b['tempo_ms'] / 1000:.0f}s" for b in boots)
        falhos = max((b.get("servicos_falhos") or 0) for b in boots) if boots else 0
        add("boot_lento_ou_com_erro",
            "Subida do servidor demorada ou concluida com erro",
            "media",
            f"{len(boots)} subida(s) no periodo: {tempos}."
            + (f" {len(com_erro)} terminou com a marca started (with errors)." if com_erro else "")
            + (f" Ate {falhos} servicos falharam ou ficaram sem dependencia." if falhos else ""),
            "server.log (WFLYSRV0025/0026)",
            "O tempo de subida define a janela minima de manutencao. Servico falho na "
            "subida deixa a rotina correspondente fora do ar sem erro na tela.")

    sf = ciclo.get("servicos_falhos") or []
    if sf:
        lista = ", ".join(x["servico"] for x in sf[:5])
        add("servicos_nao_subiram",
            "Componentes que nao entraram no ar na subida",
            "alta",
            f"{len(sf)} servico(s) distinto(s) falharam: {lista}"
            + (" e outros." if len(sf) > 5 else "."),
            "server.log (WFLYCTL0186)",
            "A tela de cada componente afetado nao responde, e o usuario relata isso como "
            "lentidao porque ela nunca abre. Conferir a causa de cada um: contexto web "
            "duplicado e servico externo indisponivel na subida sao as duas mais comuns.")

    orfas = ciclo.get("threads_nao_encerradas_total") or 0
    redeploys = ciclo.get("redeploys_total") or 0
    if orfas:
        add("threads_orfas_no_redeploy",
            "Threads de modulo nao encerradas na republicacao",
            "media",
            f"{orfas} falha(s) de interrupcao de thread em {redeploys} republicacao(oes) "
            f"de modulo no periodo.",
            "server.log",
            "Thread orfa mantem viva a referencia ao carregador de classes do modulo "
            "antigo, e com ele todas as classes dele. O consumo de memoria permanente "
            "cresce a cada republicacao e so volta ao normal com reinicio.")

    mig = ciclo.get("migracao_falhas_total") or 0
    if mig:
        porm = ciclo.get("migracao_falhas_por_modulo") or []
        piores = ", ".join(f"{x['modulo']} ({x['falhas']})" for x in porm[:4])
        add("migracao_com_falha",
            "Scripts de migracao de modulo falhando na subida",
            "alta" if mig >= 50 else "media",
            f"{mig} falha(s) de script na migracao de dicionario ou de scripts. "
            f"Maiores: {piores}.",
            "server.log (ddmigration / scriptmigration)",
            "Alteracao de estrutura que falha deixa a tabela no estado anterior. Se o "
            "codigo do modulo ja espera a coluna nova, o erro reaparece em execucao sem "
            "relacao aparente com a subida. Encaminhar por origem: modulo de produto para "
            "a Sankhya, modulo com sufixo do cliente para o autor da personalizacao.")

    # --- CPU por familia de thread
    fam = ((ev.get("threads_dump") or {}).get("cpu_por_familia") or {}).get("familias") or []
    infra = [f for f in fam if f["familia"] in ("Cluster em memória", "Varredura de deploy")]
    req = next((f for f in fam if f["familia"] == "Atendimento de requisição"), None)
    if infra and req:
        pct_infra = sum(f["pct_das_vivas"] for f in infra)
        if pct_infra >= 40 and req["pct_das_vivas"] < 5:
            detalhe = ", ".join(f"{f['familia']} {f['pct_das_vivas']:.1f}% em {f['threads']} threads"
                                for f in infra)
            add("cpu_em_infraestrutura",
                "Infraestrutura interna consome a CPU que o atendimento nao usa",
                "alta",
                f"{pct_infra:.1f}% da CPU acumulada pelas threads vivas esta em "
                f"infraestrutura ({detalhe}), contra {req['pct_das_vivas']:.2f}% no "
                f"atendimento de requisicao.",
                "threads.dump",
                "Custo fixo de CPU, independente de usuario: em producao ele se soma a "
                "carga real e reduz a folga no pico. Avaliar desligar a varredura "
                "automatica de deploy e revisar a participacao no cluster em memoria. "
                "Ressalva: cpu_ms e acumulado na vida de cada thread, e thread de "
                "requisicao e curta, entao a fatia dela e piso.")

    # --- threads
    th = ev.get("threads_dump") or {}
    if th:
        bloq = len(th.get("bloqueadas", []))
        if bloq >= 5:
            add("threads_bloqueadas",
                "Threads bloqueadas no momento do dump",
                "alta" if bloq >= 15 else "media",
                f"{bloq} thread(s) em BLOCKED de {th.get('total')} no total.",
                "threads.dump",
                "Contencao em monitor Java. Identificar o dono do lock nas pilhas.")

    # --- monitor de consultas
    mon = ev.get("monitor") or {}
    if mon and not mon.get("erro"):
        for c in mon.get("ofensivas", [])[:10]:
            if c["classe"] in ("critica", "alta"):
                objetos = ", ".join(c["objetos"][:3]) or "objeto nao identificado"
                origem = c["origens"][0]["origem"] if c["origens"] else "origem nao identificada"
                add("monitor_consulta_ofensiva",
                    f"Consulta com pontuacao {c['pontuacao']} sobre {objetos}",
                    "alta" if c["classe"] == "alta" else "critica",
                    f"{c['execucoes']} execucoes, media de {c['tempo_medio_ms']} ms, "
                    f"maximo de {c['tempo_max_ms']} ms, {c['pct_tempo_periodo']}% do tempo "
                    f"capturado. Origem: {origem}.",
                    "Monitor de Consultas",
                    "Levar a consulta ao plano de execucao antes de concluir causa. A "
                    "pontuacao ordena o trabalho; ela nao distingue falta de indice de "
                    "volume legitimo.")
        if mon.get("acima_de_5s"):
            add("monitor_execucao_travada",
                "Execucoes acima de 5 segundos no monitor",
                "alta",
                f"{mon['acima_de_5s']} execucao(oes) acima de 5 s; maximo de "
                f"{mon['maximo_ms']} ms em {mon['consultas_capturadas']} capturadas.",
                "Monitor de Consultas",
                "Execucao isolada nessa faixa e travada percebida pelo usuario. Cruzar o "
                "horario com bloqueio no banco e com o pico de conexoes.")
        if mon.get("erros_total"):
            add("monitor_consulta_com_erro",
                "Consultas com erro registradas no monitor",
                "alta",
                f"{mon['erros_total']} ocorrencia(s) com marcador de erro em "
                f"{len(mon.get('erros', []))} consulta(s) distintas.",
                "Monitor de Consultas",
                "Erro de banco em consulta e defeito, nao lentidao: tratar antes de "
                "qualquer ajuste de performance. Encaminhar ao dono do objeto.")
        if mon.get("requisicoes_com_erro"):
            add("monitor_requisicao_com_erro",
                "Execucoes originadas de requisicao que terminou em erro",
                "media",
                f"{mon['requisicoes_com_erro']} de {mon['consultas_capturadas']} execucoes "
                f"partem de pilha com pagina de erro.",
                "Monitor de Consultas (pilha)",
                "A consulta pode ter executado bem e a requisicao falhado depois. Confrontar "
                "com as excecoes do log de aplicacao no mesmo periodo.")
        for a in mon.get("atencao", []):
            if a["rotulo"] == "suspeita_n_mais_1" and a["execucoes"] >= 1000:
                add("monitor_n_mais_1",
                    "Mesma consulta repetida milhares de vezes",
                    "media",
                    f"{a['consultas']} consulta(s) com {a['execucoes']} execucoes somadas e "
                    f"tempo unitario baixo, {a['tempo_ms']} ms no total.",
                    "Monitor de Consultas",
                    "Padrao de consulta dentro de laco. Verificar se a rotina pode buscar em "
                    "lote. Importacao e processamento em lote repetem por natureza: confirmar "
                    "antes de apontar defeito.")
        if mon.get("truncado") or mon.get("fingerprints_descartados"):
            add("monitor_parcial",
                "Coleta do monitor parcial",
                "baixa",
                f"truncado={bool(mon.get('truncado'))}, "
                f"consultas descartadas por teto={mon.get('fingerprints_descartados', 0)}.",
                "Monitor de Consultas",
                "O documento tem de declarar o resultado como parcial na secao de limitacoes.")

    ordem = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    achados.sort(key=lambda a: ordem.get(a["severidade"], 9))
    return achados


# ---------------------------------------------------------------- resumo
def escrever_resumo(ev, caminho):
    L = []
    a = ev["ambiente"]
    L.append("# Resumo da coleta\n")
    L.append(f"Pacote: `{ev['meta']['pacote']}`  \nColetado em: {ev['meta']['coletado_em']}  \n"
             f"Tempo de varredura: {ev['meta']['duracao_s']} s\n")

    L.append("## Ambiente\n")
    for k in ("empresa", "versao_sankhyaw", "versao_servidor", "java", "jvm",
              "sistema_operacional", "memoria_heap", "encoding_arquivo"):
        if a.get(k):
            L.append(f"- **{k}**: {a[k]}")
    if a.get("xms_mb"):
        L.append(f"- **heap configurada**: Xms {a['xms_mb']} MB / Xmx {a['xmx_mb']} MB · GC: {a.get('gc') or 'padrao'}")
    if a.get("datasource"):
        L.append(f"- **datasource**: {a['datasource']}")
    if a.get("modulos"):
        L.append(f"- **modulos**: {len(a['modulos'])} versionados (mge {a['modulos'].get('mge','?')})")
    L.append("")

    lg = ev.get("logs") or {}
    if lg:
        L.append("## Logs de aplicacao\n")
        L.append(f"- arquivos: {len(lg['arquivos'])} · linhas: {lg['linhas']:,} · "
                 f"{lg['bytes']/1048576:.0f} MB" + (" (**truncado**)" if lg["truncado"] else ""))
        L.append(f"- periodo: {lg['periodo']['inicio']} a {lg['periodo']['fim']}")
        L.append(f"- niveis (linhas com cabecalho): {lg['por_nivel']}")
        L.append(f"- **eventos de erro: {lg['total_eventos_erro']:,} em {lg['total_eventos']:,} eventos** "
                 f"({lg['total_eventos_erro']/max(lg['total_eventos'],1)*100:.1f}%) — "
                 f"{lg['linhas_stacktrace']:,} linhas de continuacao de stacktrace excluidas")
        if lg.get("hora_pico_erros"):
            L.append(f"- hora com mais erros: {lg['hora_pico_erros']['hora']} "
                     f"({lg['hora_pico_erros']['erros']} erros)")
        if lg.get("sinais"):
            L.append(f"- sinais: {lg['sinais']}")
        # Tres linhas, nao dez. O resumo orienta a proxima leitura; o inventario
        # completo sai de `consultar.py --o excecoes`, e mante-lo aqui era pagar
        # o mesmo conteudo duas vezes em toda analise.
        exc = lg.get("excecoes", [])
        L.append("\n### Excecoes mais frequentes\n")
        L.append("| # | assinatura | ocorrencias | janela |")
        L.append("|---|---|---:|---|")
        for i, e in enumerate(exc[:3], 1):
            L.append(f"| {i} | `{e['assinatura'][:88]}` | {e['ocorrencias']} | {e['primeira']} a {e['ultima']} |")
        if len(exc) > 3:
            L.append(f"\n{len(exc)} assinaturas distintas. As demais, com a linha de amostra "
                     "de cada uma: `--o excecoes --verbose`.")
        if lg.get("oracle"):
            ora = lg["oracle"]
            top = ", ".join(f"**{o['codigo']}** ({o['ocorrencias']}x)" for o in ora[:4])
            L.append(f"\n### Codigos ORA\n\n{len(ora)} codigos distintos. Mais frequentes: "
                     f"{top}. Lista completa com o significado: `--o oracle`.")
        if lg.get("jobs"):
            L.append("\n### Jobs com tempo medido (top 10 por tempo total)\n")
            L.append("| job | exec | total ms | media ms | max ms |")
            L.append("|---|---:|---:|---:|---:|")
            for j in lg["jobs"][:10]:
                L.append(f"| {j['job'][:60]} | {j['execucoes']} | {j['tempo_total_ms']} | "
                         f"{j['tempo_medio_ms']} | {j['tempo_max_ms']} |")
        L.append("")

    d = ev.get("dml")
    if d:
        L.append("## Estatisticas de DML\n")
        L.append(f"- {d['arquivos']} arquivos · {d['linhas']:,} linhas · "
                 f"{d['linhas_descartadas']} descartadas por medida invalida")
        L.append("\n### Objetos de maior tempo total\n")
        L.append("| objeto | op | exec | total ms | media ms | limite | excesso |")
        L.append("|---|---|---:|---:|---:|---:|---:|")
        for o in d["objetos"][:6]:
            lim = o["limite_ms"] or "-"
            exc = f"{o['excesso_pct']:+.0f}%" if o.get("excesso_pct") is not None else "-"
            L.append(f"| {o['objeto']} | {o['operacao']} | {o['execucoes']} | {o['tempo_total_ms']} | "
                     f"{o['tempo_medio_ms']} | {lim} | {exc} |")
        if d["violacoes_limite"]:
            L.append(f"\n**{len(d['violacoes_limite'])} objeto(s) acima do tempo de referencia do checklist.**")
        if len(d["objetos"]) > 6:
            L.append(f"\n{len(d['objetos'])} objetos medidos. Ranking completo: `--o dml --n 30`.")
        L.append("")

    c = ev.get("conexoes")
    if c:
        L.append("## Conexoes\n")
        L.append(f"- {c['amostras']} amostras a cada {c['intervalo_minutos']} min · "
                 f"media {c['media']} · p95 {c['p95']} · pico {c['maximo']} em {c['pico']['quando']}")
        L.append("")

    t = ev.get("threads_dump")
    if t:
        L.append("## Threads\n")
        L.append(f"- {t['total']} threads em {t['gerado_em']} · estados: {t['por_estado']}")
        if t["bloqueadas"]:
            L.append(f"- {len(t['bloqueadas'])} bloqueadas")
        L.append("")

    mon = ev.get("monitor")
    if mon and not mon.get("erro"):
        L.append("## Monitor de Consultas\n")
        L.append(f"- {mon['consultas_capturadas']:,} execucoes · "
                 f"{mon['consultas_distintas']:,} consultas distintas · "
                 f"tempo somado {mon['tempo_total_ms']/1000:.1f} s"
                 + ("  (**truncado**)" if mon.get("truncado") else ""))
        L.append(f"- media {mon['tempo_medio_ms']} ms · p95 {mon['p95_ms']} ms · "
                 f"p99 {mon['p99_ms']} ms · maximo {mon['maximo_ms']} ms")
        L.append(f"- acima de 1 s: {mon['acima_de_1s']} · acima de 5 s: {mon['acima_de_5s']} · "
                 f"consultas com media acima de 1 s: {mon['consultas_lentas']}")
        cb = mon.get("cobertura") or {}
        L.append(f"- origem identificada: {cb.get('com_runtime_info', 0)} por Runtime-info, "
                 f"{cb.get('so_pilha', 0)} pela pilha, {cb.get('sem_origem', 0)} sem origem")
        L.append("\n### Consultas ofensivas (top 10 por pontuacao)\n")
        L.append("| pont | classe | cmd | objetos | exec | media ms | max ms | % tempo | origem |")
        L.append("|---:|---|---|---|---:|---:|---:|---:|---|")
        for x in mon.get("ofensivas", [])[:10]:
            org = x["origens"][0]["origem"] if x["origens"] else "-"
            L.append(f"| {x['pontuacao']} | {x['classe']} | {x['comando']} | "
                     f"{','.join(x['objetos'][:2]) or '-'} | {x['execucoes']:,} | "
                     f"{x['tempo_medio_ms']} | {x['tempo_max_ms']} | "
                     f"{x['pct_tempo_periodo']}% | {org[:34]} |")
        if mon.get("atencao"):
            L.append("\n### Pontos de atencao\n")
            L.append("| ponto | consultas | execucoes | tempo ms |")
            L.append("|---|---:|---:|---:|")
            for a in mon["atencao"]:
                L.append(f"| {a['titulo']} | {a['consultas']} | {a['execucoes']:,} | "
                         f"{a['tempo_ms']:,} |")
        if mon.get("contexto"):
            L.append("\nContexto (nao e apontamento): " + " · ".join(
                f"{c['titulo']} — {c['consultas']} consultas, {c['execucoes']:,} execucoes"
                for c in mon["contexto"]))
        L.append("\n### Consultas com erro\n")
        if mon.get("sem_marcador_de_erro"):
            L.append("Nenhum marcador de erro no log do monitor deste pacote."
                     + (f" {mon['requisicoes_com_erro']} execucoes partem de requisicao que "
                        f"terminou em pagina de erro." if mon.get("requisicoes_com_erro") else ""))
        else:
            L.append("| marcador | ocorrencias | objetos | origem |")
            L.append("|---|---:|---|---|")
            for e in mon.get("erros", [])[:10]:
                L.append(f"| {e['marcador']} | {e['ocorrencias']} | "
                         f"{','.join(e['objetos'][:2]) or '-'} | {(e['origem'] or '-')[:34]} |")
        L.append("")
    elif mon and mon.get("erro"):
        L.append(f"## Monitor de Consultas\n\n**{mon['erro']}**\n")

    ac = ev.get("acessos")
    if ac:
        L.append("## Acessos\n")
        L.append(f"- {ac['eventos']:,} eventos em {ac['dias']} dias · {ac['sessoes_distintas']} sessoes distintas")
        L.append(f"- top telas: " + ", ".join(f"{x['chave']} ({x['ocorrencias']})" for x in ac["top_telas"][:5]))
        L.append("")

    wf = ev.get("wildfly") or {}
    if wf and not wf.get("erro"):
        L.append("## Servidor de aplicacoes x pacote de referencia\n")
        L.append(f"- cliente: **WildFly {wf.get('versao_cliente')}** · referencia: "
                 f"**{wf['baseline']['versao']}** ({wf['baseline']['pacote']})"
                 + ("  ← **desatualizado**" if wf.get("desatualizado") else ""))
        if wf.get("banco"):
            L.append(f"- banco: {wf['banco'][0]['banner']}")
        if wf.get("drivers"):
            L.append("\n### Drivers de banco carregados\n")
            L.append(f"{len(wf['drivers'])} carregados. Detalhe de todos: `--o drivers`.\n")
            L.append("| classe | versao cliente | versao referencia | situacao |")
            L.append("|---|---|---|---|")
            # so os que divergem do baseline; "em dia" nao merece linha propria
            for d in [x for x in wf["drivers"]
                      if x.get("atrasado") or x.get("descontinuado")]:
                sit = ("descontinuado" if d.get("descontinuado")
                       else "atrasado" if d.get("atrasado") else "em dia")
                L.append(f"| `{d['classe']}` | {d['versao_cliente']} | "
                         f"{d['versao_referencia'] or '-'} | {sit} |")
        if wf.get("drivers_invalidos"):
            L.append("\n**JAR de driver nao resolvido:** " +
                     ", ".join(f"{d['jar']} ({d['ocorrencias']}x)" for d in wf["drivers_invalidos"]))
        L.append(f"\n### Argumentos: {len(wf.get('ausentes', []))} ausentes · "
                 f"{len(wf.get('divergentes', []))} divergentes · "
                 f"{len(wf.get('extras', []))} extras · "
                 f"{len(wf.get('ausentes_condicionais', []))} nao aplicaveis (banco/SO)\n")
        if wf.get("dimensionamento"):
            L.append("Dimensionamento (o baseline e ponto de partida da instalacao, nao "
                     "recomendacao de porte): "
                     + ", ".join(f"`{a['argumento']}` {a['valor_cliente']} "
                                 f"(base {a['valor_referencia']})"
                                 for a in wf["dimensionamento"]) + "\n")
        if wf.get("divergentes"):
            L.append("| argumento | cliente | referencia |")
            L.append("|---|---|---|")
            for a in wf["divergentes"]:
                L.append(f"| `{a['argumento']}` | {a['valor_cliente']} | {a['valor_referencia']} |")
            L.append("")
        if wf.get("ausentes"):
            L.append("Ausentes: " + ", ".join(
                f"`{a['argumento']}" + (f"={a['valor_referencia']}`" if a["valor_referencia"] else "`")
                for a in wf["ausentes"]))
        if wf.get("extras"):
            # A lista inteira custava ~320 tokens em toda analise, e a maior parte
            # e funcionalidade legitima. Contagem aqui, lista em `--o wildfly`.
            L.append(f"\n{len(wf['extras'])} argumentos existem no cliente e nao no "
                     "baseline, em regra funcionalidade legitima. Lista: `--o wildfly`.")
        L.append("")

    bc = ev.get("banco") or {}
    if bc:
        L.append("## Banco de dados em uso\n")
        if bc.get("dialeto"):
            L.append(f"- **{bc['nome']}**"
                     + (f" {bc['versao']}" if bc.get("versao") else "")
                     + f" · detectado por: {bc['fonte']}")
            L.append(f"- evidencia: `{bc['evidencia']}`")
        else:
            L.append("- **dialeto nao identificado.** Sem URL de datasource, banner "
                     "no log ou driver unico, o pacote nao responde qual banco esta "
                     "em uso, e nenhum script pode ser entregue ao cliente.")
        if bc.get("conflito"):
            c = bc["conflito"]
            L.append(f"- **fontes discordam:** URL diz `{c['url']['dialeto']}`, "
                     f"banner diz `{c['banner']['dialeto']}`. {c['leitura']}")
        if len(bc.get("drivers_carregados") or []) > 1:
            L.append("- mais de um dialeto entre os drivers carregados ("
                     + ", ".join(bc["drivers_carregados"])
                     + "): driver carregado nao decide o banco em uso.")
        s = bc.get("scripts") or {}
        if s.get("aplicaveis"):
            L.append("\n### Scripts aplicaveis\n")
            L.append("| id | tipo | origem | arquivo |")
            L.append("|---|---|---|---|")
            for x in s["aplicaveis"]:
                L.append(f"| {x['id']} | {x['tipo']} | {x.get('origem') or '-'} | "
                         f"`{x['arquivo']}` |")
        if s.get("lacunas"):
            L.append("\n**Sem script para este dialeto:** "
                     + ", ".join(x["id"] for x in s["lacunas"]))
        L.append("")

    L.append("## Achados automaticos\n")
    L.append("| severidade | achado | evidencia |")
    L.append("|---|---|---|")
    for x in ev["achados"]:
        L.append(f"| {x['severidade']} | {x['titulo']} | {x['evidencia'][:120]} |")
    L.append("\n> Achado automatico e ponto de partida. A leitura de causa, o cruzamento entre "
             "fontes e a priorizacao sao do analista sobre o `evidencias.json`.\n")

    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ------------------------------------------------------------ separacao
# Series densas: milhares de pontos que so os graficos consomem. Mantidas no
# evidencias.json, elas respondem por mais da metade do arquivo, e uma leitura
# distraida do JSON inteiro custa mais de 190 mil tokens de contexto — quase tudo
# em numeros que ninguem le. Vao para series.json, com um ponteiro no lugar.
SERIES_DENSAS = [
    ("conexoes", "serie"),
    ("logs", "por_hora"),
]


def separar_series(ev):
    series = {}
    for bloco, chave in SERIES_DENSAS:
        dado = (ev.get(bloco) or {}).get(chave)
        if not dado:
            continue
        series[f"{bloco}.{chave}"] = dado
        ev[bloco][chave] = {
            "movido_para": "series.json",
            "chave": f"{bloco}.{chave}",
            "pontos": len(dado),
        }
    if series:
        ev.setdefault("meta", {})["series_em"] = "series.json"
    return series


def obter_serie(ev, bloco, chave, dir_base):
    """Le uma serie densa, do proprio ev ou do series.json ao lado."""
    dado = (ev.get(bloco) or {}).get(chave)
    if isinstance(dado, list):
        return dado                       # coleta antiga, tudo num arquivo so
    if isinstance(dado, dict) and dado.get("movido_para"):
        caminho = os.path.join(dir_base, dado["movido_para"])
        if os.path.exists(caminho):
            with open(caminho, encoding="utf-8") as f:
                return json.load(f).get(dado["chave"], [])
    return []


# -------------------------------------------------- pacote do monitor ao lado
def achar_monitor_ao_lado(pacote):
    """Procura o pacote do Monitor de Consultas na mesma pasta do pacote de log.

    O cliente manda os dois juntos e o nome do segundo vem do navegador
    (`Monitoramento (15).zip`), sem padrao. Reconhecer pelo conteudo evita
    depender do nome, e evita que o analista esqueca de passar `--monitor`.
    """
    pasta = os.path.dirname(os.path.abspath(pacote)) or "."
    alvo = os.path.abspath(pacote)
    candidatos = []
    try:
        nomes = os.listdir(pasta)
    except OSError:
        return None
    for n in nomes:
        p = os.path.join(pasta, n)
        if os.path.abspath(p) == alvo or not n.lower().endswith(".zip"):
            continue
        try:
            if coletar_monitor.e_pacote_de_monitor(p):
                candidatos.append(p)
        except Exception:
            continue
    if not candidatos:
        return None
    # mais de um: o maior, que e o de coleta mais longa
    candidatos.sort(key=lambda p: -os.path.getsize(p))
    if len(candidatos) > 1:
        print(f"  {len(candidatos)} pacotes de monitor na pasta; usando o maior: "
              f"{os.path.basename(candidatos[0])}", file=sys.stderr)
    return candidatos[0]


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Coleta metricas do pacote de log do Sankhya.")
    ap.add_argument("--pacote", required=True, help="arquivo .zip do pacote ou pasta ja extraida")
    ap.add_argument("--saida", default=".", help="pasta de saida (default: atual)")
    ap.add_argument("--rapido", action="store_true",
                    help="le no maximo 200 MB por arquivo de log; usar so para inspecao previa")
    ap.add_argument("--monitor", default=None,
                    help="pacote do Monitor de Consultas (zip ou pasta). Sem isto, procura "
                         "um ao lado do pacote de log")
    ap.add_argument("--sem-monitor", action="store_true",
                    help="ignora o pacote do monitor mesmo quando existe ao lado")
    args = ap.parse_args()

    if not os.path.exists(args.pacote):
        print(f"Pacote nao encontrado: {args.pacote}", file=sys.stderr)
        return 2
    os.makedirs(args.saida, exist_ok=True)

    caminho_monitor = None
    if not args.sem_monitor:
        caminho_monitor = args.monitor or achar_monitor_ao_lado(args.pacote)
        if args.monitor and not os.path.exists(args.monitor):
            print(f"Pacote do monitor nao encontrado: {args.monitor}", file=sys.stderr)
            return 2

    t0 = time.time()
    fonte = Fonte(args.pacote)
    ev = {"meta": {
        "pacote": os.path.abspath(args.pacote),
        "coletado_em": agora(),
        "arquivos_no_pacote": len(fonte.nomes),
        "bytes_no_pacote": sum(fonte._tam.values()),
        "modo": "rapido" if args.rapido else "completo",
        "versao_coletor": "1.1",
        "pacote_monitor": caminho_monitor,
    }}

    etapas = [
        ("ambiente", lambda: bloco_ambiente(fonte)),
        ("diagnostico", lambda: bloco_diagnostico(fonte)),
        ("logs", lambda: bloco_logs(fonte, args.rapido)),
        ("monitor", (lambda: coletar_monitor.bloco_monitor(caminho_monitor))
                    if caminho_monitor else (lambda: None)),
        ("dml", lambda: bloco_dml(fonte)),
        ("conexoes", lambda: bloco_conexoes(fonte)),
        ("threads_dump", lambda: bloco_threads(fonte)),
        ("acessos", lambda: bloco_acessos(fonte)),
        ("licencas", lambda: bloco_licencas(fonte)),
        # depende de ambiente e logs ja coletados
        ("wildfly", lambda: bloco_wildfly(ev)),
        ("banco", lambda: bloco_banco(ev)),
    ]
    for nome, fn in etapas:
        marca = time.time()
        try:
            ev[nome] = fn()
        except Exception as e:  # uma fonte corrompida nao pode derrubar a coleta
            ev[nome] = None
            ev.setdefault("falhas", []).append({"etapa": nome, "erro": f"{type(e).__name__}: {e}"})
        print(f"  {nome}: {time.time() - marca:.1f}s", file=sys.stderr)

    ev["achados"] = gerar_achados(ev)
    ev["meta"]["duracao_s"] = round(time.time() - t0, 1)

    series = separar_series(ev)

    p_json = os.path.join(args.saida, "evidencias.json")
    p_series = os.path.join(args.saida, "series.json")
    p_md = os.path.join(args.saida, "resumo.md")
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=1)
    with open(p_series, "w", encoding="utf-8") as f:
        json.dump(series, f, ensure_ascii=False, separators=(",", ":"))
    escrever_resumo(ev, p_md)

    kb = lambda p: os.path.getsize(p) / 1024
    print(f"\nOK  {p_json}   ({kb(p_json):.0f} KB)"
          f"\nOK  {p_series}   ({kb(p_series):.0f} KB, só para os gráficos)"
          f"\nOK  {p_md}   ({kb(p_md):.0f} KB)"
          f"\n{len(ev['achados'])} achado(s) automatico(s) em {ev['meta']['duracao_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
