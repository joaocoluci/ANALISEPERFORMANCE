#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Coletor do pacote do Monitor de Consultas do Sankhya.

O pacote e um zip com dois arquivos que se referenciam pelo mesmo identificador
de bloco (`##ID_n##`):

  Monitor_Consulta.log   tempo, Runtime-info (quando ha), SQL e `Params:`
  Monitor_Processos.log   a pilha Java que originou aquele mesmo ID

Sem o segundo arquivo a origem da consulta fica em branco na maioria dos blocos:
num pacote medido, so 553 de 16.013 blocos traziam Runtime-info. A pilha responde
"quem chamou" nos outros 15.460.

  python coletar_monitor.py --monitor "Monitoramento (15).zip" --saida ./analise

Le por streaming; nada e descompactado em disco. Sem dependencia externa.

--------------------------------------------------------------- o que nao coleta

`Params:` traz valor de negocio do cliente — CPF, valor de titulo, nome. Aqui so
entra a CONTAGEM de parametros. Valor de parametro nao vai para o JSON e nao vai
para o documento.

------------------------------------------------------------------- pontuacao

Pontuacao de ofensa, 0 a 100, quatro fatores somados:

  peso no periodo   0-40   tempo total da consulta / tempo total capturado
  lentidao unitaria 0-30   media por execucao, em escala log a partir de 100 ms
  repeticao         0-20   execucoes em escala log; pega N+1 com media de 2 ms
  cauda             0-10   p95 e maximo acima de 1 s / 5 s

Faixas: critica >= 70, alta 50-69, media 30-49, baixa < 30.

A pontuacao ordena o trabalho; ela nao prova causa. Uma consulta de 90 pontos
pode estar lenta por falta de indice, por estatistica velha ou por volume
legitimo — o pacote do monitor nao distingue os tres.
"""

import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict

ENC = "cp1252"          # mesmo file.encoding do WildFly Sankhya

# ---------------------------------------------------------------- limiares
CORTE_MEDIA_MS = 100        # abaixo disso a consulta nao pontua por lentidao
CORTE_LENTA_MS = 1000       # media acima disso e lenta por si so
CORTE_CAUDA_MS = 5000       # execucao isolada acima disso e travada percebida
CORTE_N1_EXEC = 100         # repeticao a partir daqui, com media baixa, sugere N+1
CORTE_N1_MEDIA_MS = 50
CORTE_PROJECAO_LARGA = 50   # colunas na projecao

FAIXAS = [                  # rotulo, limite superior exclusivo em ms
    ("até 10 ms", 10),
    ("10 a 100 ms", 100),
    ("100 ms a 1 s", 1000),
    ("1 s a 5 s", 5000),
    ("acima de 5 s", None),
]

# Teto de memoria. Pacote grande nao pode derrubar a coleta; quando estoura, o
# JSON diz que estourou e o documento tem de declarar o resultado como parcial.
MAX_FINGERPRINTS = 20000
MAX_IDS_PILHA = 400000
MAX_AMOSTRAS_TEMPO = 2000   # por fingerprint, para o p95

# ---------------------------------------------------------------- padroes
P_SEPARADOR = re.compile(r"^-{40,}\s*$")
P_CABECALHO = re.compile(r"^##ID_(\d+)##(?:\s+tempo:\s*(\d+))?")
P_PARAM = re.compile(r"^\s{1,4}\d+\s*=")
P_RUNTIME_CHAVE = re.compile(r"^([A-Za-z][\w-]*):\s*(.*)$")

# Marcador de erro no proprio log do monitor. Nem todo pacote traz erro: quando
# nao traz, o relatorio diz isso com essas palavras, em vez de omitir a subsecao.
#
# O codigo do banco vem primeiro de proposito. Na linha
# `java.sql.SQLSyntaxErrorException: ORA-00904: ...` o nome da classe aparece
# antes, e um regex unico devolveria `SQLSyntaxErrorException` — que nao diz qual
# foi o erro. `ORA-00904` diz, e casa com o catalogo de codigos do coletor.
P_ERRO_CODIGO = re.compile(r"(ORA-\d{5}|JZ\d{3}|Msg \d{4}, Level \d+)")
P_ERRO_TEXTO = re.compile(
    r"(SQLServerException"
    r"|SQLSyntaxErrorException"
    r"|SQLIntegrityConstraintViolationException"
    r"|SQLTimeoutException"
    r"|SQLException"
    r"|BatchUpdateException"
    r"|ERROR:)")


def _marcador_erro(texto):
    """Codigo do banco quando existe; senao a classe da excecao."""
    m = P_ERRO_CODIGO.search(texto) or P_ERRO_TEXTO.search(texto)
    return m.group(1) if m else None

# Frames que dizem "esta requisicao terminou em erro". Sao da pilha, nao do SQL:
# a consulta pode ter executado bem e a requisicao ter falhado depois.
PILHA_ERRO = ("SendErrorPageHandler", "MGEModelException", "ErrorPageHandler",
              "DefaultErrorHandler", "ExceptionHandler")

# Execucao fora de requisicao de usuario. `BackgroundProcessSP` fica de fora de
# proposito: e o servico que a TELA chama para perguntar o andamento do processo,
# e roda dentro da requisicao do usuario. Sem essa exclusao, toda tela que
# acompanha uma importacao entra no relatorio como execucao em background.
PILHA_BACKGROUND = ("BackgroundProcess", "ScheduledAction", "QuartzScheduler",
                    "org.quartz", "TimerService", "JobExecutor")
PILHA_BACKGROUND_EXCLUSAO = ("BackgroundProcessSP",)

# Infraestrutura: aparece em toda pilha e nunca responde "quem chamou".
# A ordem nao importa; e teste de prefixo.
FRAME_INFRA = (
    "br.com.sankhya.jape", "br.com.sankhya.ws", "br.com.sankhya.dwf",
    "br.com.sankhya.ag.lstbrk", "br.com.sankhya.modelcore.dwfdata.Connection",
    "br.com.sankhya.modelcore.util.JapeSessionContext",
    "com.sun.proxy", "io.undertow", "javax.servlet", "org.jboss", "org.wildfly",
    "org.apache", "java.", "javax.", "jdk.", "sun.", "com.arjuna",
    # motor de script e container de EJB: aparecem entre o script do cliente e o
    # produto, e escolher um deles como origem devolve "bsh.Reflect.invokeOnMethod",
    # que nao diz nada a quem vai corrigir
    "bsh.", "org.tinyejb", "net.sf.cglib", "org.mozilla.javascript",
    # frame de excecao: diz que houve erro, nao quem chamou a consulta
    "br.com.sankhya.modelcore.MGEModelException",
)

# Motor de script: quando aparece na pilha, a consulta nasceu em evento
# programavel / regra escrita fora do produto, ainda que o frame de negocio
# abaixo dele seja do produto.
PILHA_SCRIPT = ("bsh.", "org.mozilla.javascript", "javax.script")

# Objeto personalizado: campo/tabela AD_, procedure custom, ou pacote que nao e
# do produto. `AD_` sozinho nao serve — a coluna AD_ em tabela padrao aparece em
# quase todo SELECT gerado pelo dicionario.
P_OBJETO_AD = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO|CALL)\s+(AD_\w+)", re.I)
P_STP_AD = re.compile(r"\b(STP_AD_\w+|AD_STP_\w+)", re.I)

P_TABELAS = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INSERT\s+INTO|DELETE\s+FROM)\s+([A-Za-z_][\w$]*)", re.I)
P_CALL = re.compile(r"\{\s*call\s+([\w$]+)", re.I)


# --------------------------------------------------------- pontos de atencao
# Rotulo de contexto explica ONDE a consulta roda; nao e apontamento e nao entra
# na lista de pontos de atencao do documento. Sem essa separacao, um pacote de
# importacao em massa abre o relatorio com "execucao em background" no topo, que
# nao e defeito nenhum.
ATENCAO_CONTEXTO = ("execucao_em_background",)

# rotulo -> (titulo, o que a evidencia mostra, o que ela NAO prova)
#
# A terceira coluna existe porque o erro tipico da analise nao e deixar de achar:
# e ler "sem WHERE" e escrever "falta indice" no documento do cliente.
ATENCAO_CATALOGO = {
    "sem_filtro": (
        "Comando sem cláusula de filtro",
        "O comando varre o objeto inteiro a cada execução.",
        "Não prova que o objeto é grande nem que a varredura é o gargalo: "
        "tabela pequena varrida é barata."),
    "for_update": (
        "Bloqueio explícito de linha",
        "A consulta trava a linha até o fim da transação.",
        "Não prova contenção: prova que existe bloqueio. Contenção só aparece "
        "cruzando com sessões em espera no banco."),
    "funcao_no_filtro": (
        "Função aplicada à coluna do filtro",
        "Função sobre a coluna filtrada impede o uso do índice daquela coluna.",
        "Não prova que existe índice na coluna, nem que o plano mudaria. "
        "Confirmar com o plano de execução."),
    "like_curinga_inicial": (
        "Filtro por texto com curinga à esquerda",
        "`LIKE '%valor'` não usa índice comum.",
        "Não prova que o volume filtrado é relevante."),
    "subconsulta_no_filtro": (
        "Subconsulta dentro do filtro",
        "`IN (SELECT …)` ou `EXISTS (SELECT …)` no filtro; pode reexecutar por linha.",
        "Não prova reexecução: o otimizador costuma reescrever para join. "
        "Só o plano de execução responde."),
    "distinct_com_juncao": (
        "DISTINCT sobre junção",
        "DISTINCT sobre junção normalmente compensa duplicação de linhas gerada "
        "pela própria junção, com custo de ordenação.",
        "Não prova erro de modelagem."),
    "projecao_larga": (
        "Projeção com dezenas de colunas",
        "A consulta traz o registro inteiro; tráfego e memória crescem por linha.",
        "Não prova desperdício: telas de cadastro precisam do registro completo."),
    "select_estrela": (
        "Projeção com asterisco",
        "`SELECT *` transporta colunas que a chamada pode não usar, e quebra ao "
        "mudar a estrutura do objeto.",
        "Não prova impacto de tempo."),
    "objeto_personalizado": (
        "Objeto personalizado envolvido",
        "O comando toca objeto criado fora do produto (`AD_*` ou procedure custom).",
        "Não prova que a personalização é a causa; prova que o ajuste tem dono "
        "fora da Sankhya."),
    "origem_personalizada": (
        "Chamada originada em módulo personalizado",
        "A pilha do bloco parte de pacote que não é do produto.",
        "Não prova defeito na personalização."),
    "origem_em_script": (
        "Chamada originada em script personalizado",
        "A pilha passa pelo motor de script: a consulta nasceu em evento "
        "programável ou regra escrita fora do produto.",
        "Não prova defeito no script: ele pode apenas chamar rotina do produto, "
        "que executa a consulta."),
    "suspeita_n_mais_1": (
        "Repetição alta com tempo unitário baixo",
        "A mesma consulta repete muitas vezes, rápida em cada execução: padrão de "
        "consulta dentro de laço.",
        "Não prova laço no código: importação e processamento em lote repetem a "
        "mesma consulta por natureza."),
    "execucao_em_background": (
        "Execução fora de requisição de usuário",
        "A consulta parte de processo em segundo plano ou ação agendada.",
        "Não prova que o usuário não sente: processo em background disputa banco "
        "com a operação."),
}


# ------------------------------------------------------------------ fonte
class FonteMonitor:
    """Abstrai zip do monitor e pasta ja extraida sob a mesma interface."""

    def __init__(self, caminho):
        self.caminho = caminho
        self.zip = None
        if os.path.isdir(caminho):
            self.nomes = []
            for raiz, _, arqs in os.walk(caminho):
                for a in arqs:
                    p = os.path.join(raiz, a)
                    self.nomes.append(os.path.relpath(p, caminho).replace("\\", "/"))
            self._tam = {n: os.path.getsize(os.path.join(caminho, n)) for n in self.nomes}
        else:
            self.zip = zipfile.ZipFile(caminho)
            infos = [i for i in self.zip.infolist() if not i.is_dir()]
            self.nomes = [i.filename for i in infos]
            self._tam = {i.filename: i.file_size for i in infos}

    def tamanho(self, nome):
        return self._tam.get(nome, 0)

    def abrir_texto(self, nome):
        f = self.zip.open(nome) if self.zip else open(
            os.path.join(self.caminho, nome), "rb")
        return io.TextIOWrapper(f, encoding=ENC, errors="replace")

    def achar(self, marcador):
        """Arquivos cujo nome contem o marcador, do maior para o menor."""
        alvos = [n for n in self.nomes if marcador.lower() in os.path.basename(n).lower()]
        return sorted(alvos, key=lambda n: -self.tamanho(n))


def e_pacote_de_monitor(caminho):
    """Reconhece o pacote pelo conteudo, nao pelo nome.

    O nome vem do navegador (`Monitoramento (15).zip`) e nao e confiavel.
    """
    try:
        fonte = FonteMonitor(caminho)
    except (zipfile.BadZipFile, OSError):
        return False
    return bool(fonte.achar("Monitor_Consulta"))


# ------------------------------------------------------------ normalizacao
P_LITERAL_TEXTO = re.compile(r"'(?:[^']|'')*'")
P_NUMERO = re.compile(r"\b\d+(?:\.\d+)?\b")
P_LISTA_PARAM = re.compile(r"\?(?:\s*,\s*\?)+")
P_ESPACO = re.compile(r"\s+")


def normalizar_sql(sql):
    """Reduz a consulta a uma forma comparavel entre execucoes.

    Sem isso, a mesma consulta com id diferente vira N consultas distintas e o
    peso real dela no periodo desaparece diluido.
    """
    s = P_LITERAL_TEXTO.sub("'?'", sql)
    s = P_LISTA_PARAM.sub("?", s)
    s = P_NUMERO.sub("#", s)
    s = P_ESPACO.sub(" ", s).strip()
    return s


def impressao(sql_normalizado):
    return hashlib.md5(sql_normalizado.encode("utf-8", "replace")).hexdigest()[:10]


def comando_de(sql):
    s = sql.lstrip().lstrip("(").lstrip()
    if s.startswith("{"):
        return "STP"
    p = s[:12].upper()
    for c in ("SELECT", "UPDATE", "INSERT", "DELETE", "MERGE", "ALTER", "CREATE", "DROP"):
        if p.startswith(c):
            return c
    if p.startswith("BEGIN") or p.startswith("DECLARE"):
        return "PLSQL"
    return "OUTRO"


def objetos_de(sql, comando):
    if comando == "STP":
        m = P_CALL.search(sql)
        return [m.group(1).upper()] if m else []
    vistos = []
    for m in P_TABELAS.finditer(sql):
        obj = m.group(1).upper()
        if obj in ("SELECT", "DUAL") or obj in vistos:
            continue
        vistos.append(obj)
        if len(vistos) >= 6:
            break
    return vistos


def _clausula_filtro(sql_up):
    i = sql_up.find(" WHERE ")
    return sql_up[i:] if i >= 0 else ""


P_FUNCAO_FILTRO = re.compile(
    r"\b(UPPER|LOWER|TRUNC|TO_CHAR|TO_DATE|SUBSTR|NVL|COALESCE|CAST|CONVERT|"
    r"LTRIM|RTRIM|TRIM|ISNULL|DATEDIFF|YEAR|MONTH)\s*\(\s*[A-Z_][\w$.]*\s*[),]", re.I)
P_SUB_FILTRO = re.compile(r"\b(?:IN|EXISTS|NOT\s+IN|NOT\s+EXISTS)\s*\(\s*SELECT\b", re.I)
P_LIKE_CURINGA = re.compile(r"LIKE\s*'%", re.I)


def atencao_de(sql, comando, origem):
    """Padroes visiveis no texto do comando. Cada um e ponto de atencao, nao causa."""
    up = sql.upper()
    filtro = _clausula_filtro(up)
    rotulos = []

    if comando in ("SELECT", "UPDATE", "DELETE") and " WHERE " not in up:
        # SELECT ... FROM DUAL e sequence nao sao varredura
        if " FROM DUAL" not in up and ".NEXTVAL" not in up:
            rotulos.append("sem_filtro")
    if " FOR UPDATE" in up:
        rotulos.append("for_update")
    if filtro and P_FUNCAO_FILTRO.search(filtro):
        rotulos.append("funcao_no_filtro")
    if P_LIKE_CURINGA.search(up):
        rotulos.append("like_curinga_inicial")
    if filtro and P_SUB_FILTRO.search(filtro):
        rotulos.append("subconsulta_no_filtro")
    if "SELECT DISTINCT" in up and (" JOIN " in up or up.count(",") > 3):
        rotulos.append("distinct_com_juncao")
    if comando == "SELECT":
        cabeca = up[:up.find(" FROM ")] if " FROM " in up else up
        if re.search(r"SELECT\s+(?:DISTINCT\s+)?(?:[A-Z_][\w$]*\.)?\*", cabeca):
            rotulos.append("select_estrela")
        elif cabeca.count(",") >= CORTE_PROJECAO_LARGA:
            rotulos.append("projecao_larga")
    if P_OBJETO_AD.search(sql) or P_STP_AD.search(sql):
        rotulos.append("objeto_personalizado")
    if origem and origem.get("personalizada"):
        rotulos.append("origem_personalizada")
    if origem and origem.get("script"):
        rotulos.append("origem_em_script")
    if origem and origem.get("background"):
        rotulos.append("execucao_em_background")
    return rotulos


# ------------------------------------------------------------------ pilhas
def _frame_limpo(linha):
    """`deployment.x.jar//pkg.Classe.metodo(Arq.java:12)` -> `pkg.Classe.metodo`."""
    s = linha.strip()
    if "//" in s:
        s = s.split("//", 1)[1]
    i = s.find("(")
    return s[:i] if i > 0 else s


def _e_infra(frame):
    return frame.startswith(FRAME_INFRA)


def _e_produto(frame):
    return frame.startswith(("br.com.sankhya.", "com.sankhya."))


def ler_pilhas(fonte, nomes, limite_ids=MAX_IDS_PILHA):
    """id -> origem derivada da pilha. So o que cabe em poucos bytes por id.

    Guardar a pilha inteira de 400 mil ids nao caberia em memoria e nao serviria:
    o que o diagnostico usa e o primeiro frame que nao e infraestrutura, mais tres
    marcadores.
    """
    pilhas = {}
    truncado = False
    lidos = 0
    for nome in nomes:
        with fonte.abrir_texto(nome) as f:
            atual = None
            frames = 0
            escolhido = None
            marcas = set()
            for linha in f:
                if P_SEPARADOR.match(linha):
                    continue
                m = P_CABECALHO.match(linha)
                if m:
                    if atual is not None:
                        pilhas[atual] = _montar_origem(escolhido, marcas, frames)
                    if len(pilhas) >= limite_ids:
                        truncado = True
                        atual = None
                        break
                    atual = int(m.group(1))
                    frames, escolhido, marcas = 0, None, set()
                    lidos += 1
                    continue
                if atual is None or not linha.strip():
                    continue
                frames += 1
                bruta = linha
                frame = _frame_limpo(bruta)
                if escolhido is None and not _e_infra(frame):
                    escolhido = frame
                if any(m in bruta for m in PILHA_ERRO):
                    marcas.add("erro")
                if (any(m in bruta for m in PILHA_BACKGROUND)
                        and not any(x in bruta for x in PILHA_BACKGROUND_EXCLUSAO)):
                    marcas.add("background")
                if frame.startswith(PILHA_SCRIPT):
                    marcas.add("script")
            if atual is not None:
                pilhas[atual] = _montar_origem(escolhido, marcas, frames)
        if truncado:
            break
    return pilhas, {"ids": lidos, "truncado": truncado}


def _montar_origem(frame, marcas, profundidade):
    return {
        "frame": frame,
        "erro": "erro" in marcas,
        "background": "background" in marcas,
        "script": "script" in marcas,
        "personalizada": bool(frame) and not _e_produto(frame) and not _e_infra(frame),
        "profundidade": profundidade,
    }


def _rotulo_origem(runtime, origem):
    """Nome curto de quem chamou. Runtime-info quando existe; senao a pilha."""
    if runtime:
        svc = runtime.get("service-name")
        if svc:
            return svc
        app = runtime.get("Application")
        if app:
            return app
    if origem and origem.get("frame"):
        partes = origem["frame"].split(".")
        return ".".join(partes[-2:]) if len(partes) > 2 else origem["frame"]
    if origem and origem.get("script"):
        return "(script personalizado)"
    if origem and origem.get("background"):
        return "(processo em segundo plano)"
    return "(origem não identificada)"


# ------------------------------------------------------------------ blocos
class Agregado:
    """Acumula uma consulta (por impressao do SQL) ao longo do periodo."""

    __slots__ = ("sql", "comando", "objetos", "execucoes", "tempo_ms", "maximo_ms",
                 "tempos", "origens", "aplicacoes", "servicos", "atencao",
                 "com_erro", "erros", "ids", "params")

    def __init__(self, sql, comando, objetos, atencao):
        self.sql = sql
        self.comando = comando
        self.objetos = objetos
        self.atencao = set(atencao)
        self.execucoes = 0
        self.tempo_ms = 0
        self.maximo_ms = 0
        self.tempos = []
        self.origens = Counter()
        self.aplicacoes = Counter()
        self.servicos = Counter()
        self.com_erro = 0
        self.erros = Counter()
        self.ids = []
        self.params = 0


def varrer_consultas(fonte, nomes, pilhas):
    """Percorre o Monitor_Consulta e agrega por impressao do SQL."""
    ag = {}
    faixas = [0] * len(FAIXAS)
    faixas_ms = [0] * len(FAIXAS)
    capturadas = 0
    tempo_total = 0
    maximo = 0
    fingerprints_descartados = 0
    com_runtime = 0
    so_pilha = 0
    sem_origem = 0
    requisicoes_com_erro = 0
    tempos_globais = []
    arquivos = []

    for nome in nomes:
        arquivos.append({"arquivo": nome, "bytes": fonte.tamanho(nome)})
        with fonte.abrir_texto(nome) as f:
            bloco = None
            for linha in f:
                if P_SEPARADOR.match(linha):
                    continue
                m = P_CABECALHO.match(linha)
                if m:
                    if bloco:
                        r = _fechar_bloco(bloco, pilhas, ag, faixas, faixas_ms)
                        if r:
                            capturadas += 1
                            tempo_total += r["ms"]
                            maximo = max(maximo, r["ms"])
                            if len(tempos_globais) < 200000:
                                tempos_globais.append(r["ms"])
                            com_runtime += r["com_runtime"]
                            so_pilha += r["so_pilha"]
                            sem_origem += r["sem_origem"]
                            requisicoes_com_erro += r["erro_pilha"]
                            fingerprints_descartados += r["descartado"]
                    bloco = {
                        "id": int(m.group(1)),
                        "ms": int(m.group(2) or 0),
                        "sql": [],
                        "runtime": {},
                        "params": 0,
                        "em_runtime": False,
                        "em_params": False,
                        "erro_texto": None,
                    }
                    continue
                if bloco is None:
                    continue
                _linha_do_bloco(bloco, linha)
            if bloco:
                r = _fechar_bloco(bloco, pilhas, ag, faixas, faixas_ms)
                if r:
                    capturadas += 1
                    tempo_total += r["ms"]
                    maximo = max(maximo, r["ms"])
                    tempos_globais.append(r["ms"])
                    com_runtime += r["com_runtime"]
                    so_pilha += r["so_pilha"]
                    sem_origem += r["sem_origem"]
                    requisicoes_com_erro += r["erro_pilha"]

    return {
        "ag": ag, "arquivos": arquivos, "capturadas": capturadas,
        "tempo_total_ms": tempo_total, "maximo_ms": maximo,
        "faixas": faixas, "faixas_ms": faixas_ms,
        "tempos": tempos_globais,
        "fingerprints_descartados": fingerprints_descartados,
        "cobertura": {"com_runtime_info": com_runtime, "so_pilha": so_pilha,
                      "sem_origem": sem_origem},
        "requisicoes_com_erro": requisicoes_com_erro,
    }


def _linha_do_bloco(bloco, linha):
    s = linha.rstrip("\n").rstrip("\r")
    nu = s.strip()
    if not nu:
        return

    # comentario Runtime-info que o proprio monitor injeta antes do SQL
    if nu.startswith("/*") and "Runtime-info" in nu:
        bloco["em_runtime"] = True
        return
    if bloco["em_runtime"]:
        if nu.startswith("*/"):
            bloco["em_runtime"] = False
            return
        m = P_RUNTIME_CHAVE.match(nu)
        if m:
            bloco["runtime"][m.group(1)] = m.group(2).strip()
        return

    if nu == "Params:":
        bloco["em_params"] = True
        return
    if bloco["em_params"]:
        # valor de parametro e dado do cliente: conta, nao guarda
        if P_PARAM.match(s):
            bloco["params"] += 1
        elif bloco["erro_texto"] is None:
            marcador = _marcador_erro(nu)
            if marcador:
                bloco["erro_texto"] = (marcador, nu[:160])
        return

    if bloco["erro_texto"] is None:
        marcador = _marcador_erro(nu)
        if marcador:
            bloco["erro_texto"] = (marcador, nu[:160])
            return
    if len(bloco["sql"]) < 60:
        bloco["sql"].append(nu)


def _faixa_de(ms):
    for i, (_, teto) in enumerate(FAIXAS):
        if teto is None or ms < teto:
            return i
    return len(FAIXAS) - 1


def _fechar_bloco(bloco, pilhas, ag, faixas, faixas_ms):
    sql = " ".join(bloco["sql"]).strip()
    if not sql:
        return None
    ms = bloco["ms"]
    origem = pilhas.get(bloco["id"])
    runtime = bloco["runtime"]
    normalizado = normalizar_sql(sql)
    chave = impressao(normalizado)

    descartado = 0
    item = ag.get(chave)
    if item is None:
        if len(ag) >= MAX_FINGERPRINTS:
            descartado = 1
        else:
            comando = comando_de(sql)
            item = Agregado(normalizado[:400], comando,
                            objetos_de(sql, comando),
                            atencao_de(sql, comando, origem))
            ag[chave] = item

    i = _faixa_de(ms)
    faixas[i] += 1
    faixas_ms[i] += ms

    if item is not None:
        item.execucoes += 1
        item.tempo_ms += ms
        item.maximo_ms = max(item.maximo_ms, ms)
        item.params += bloco["params"]
        if len(item.tempos) < MAX_AMOSTRAS_TEMPO:
            item.tempos.append(ms)
        if len(item.ids) < 5:
            item.ids.append(bloco["id"])
        item.origens[_rotulo_origem(runtime, origem)] += 1
        if runtime.get("Application"):
            item.aplicacoes[runtime["Application"]] += 1
        if runtime.get("service-name"):
            item.servicos[runtime["service-name"]] += 1
        if origem:
            if origem.get("personalizada"):
                item.atencao.add("origem_personalizada")
            if origem.get("script"):
                item.atencao.add("origem_em_script")
            if origem.get("background"):
                item.atencao.add("execucao_em_background")
        if bloco["erro_texto"]:
            marcador, linha = bloco["erro_texto"]
            item.com_erro += 1
            item.erros[(marcador, linha)] += 1
        if origem and origem.get("erro"):
            item.atencao.add("requisicao_com_erro")

    return {
        "ms": ms,
        "com_runtime": 1 if runtime else 0,
        "so_pilha": 1 if (not runtime and origem and origem.get("frame")) else 0,
        "sem_origem": 1 if (not runtime and not (origem and origem.get("frame"))) else 0,
        "erro_pilha": 1 if (origem and origem.get("erro")) else 0,
        "descartado": descartado,
    }


# ---------------------------------------------------------------- pontuacao
def _percentil(valores, p):
    if not valores:
        return 0
    ordenado = sorted(valores)
    i = min(len(ordenado) - 1, int(round(p * (len(ordenado) - 1))))
    return ordenado[i]


def pontuar(item, tempo_total_geral, p95):
    """Pontuacao 0-100 e as parcelas. As parcelas vao para o JSON porque o
    documento tem de poder dizer POR QUE a consulta pontuou."""
    media = item.tempo_ms / item.execucoes if item.execucoes else 0

    peso = 40.0 * (item.tempo_ms / tempo_total_geral) if tempo_total_geral else 0.0

    if media <= CORTE_MEDIA_MS:
        lentidao = 0.0
    else:
        # 100 ms = 0 · 1 s = 15 · 10 s = 30 (dois decadas de escala)
        lentidao = 30.0 * min(1.0, math.log10(media / CORTE_MEDIA_MS) / 2.0)

    repeticao = 20.0 * min(1.0, math.log10(item.execucoes) / 4.0) if item.execucoes > 1 else 0.0

    if p95 >= CORTE_CAUDA_MS:
        cauda = 10.0
    elif item.maximo_ms >= CORTE_CAUDA_MS:
        cauda = 7.0
    elif item.maximo_ms >= CORTE_LENTA_MS:
        cauda = 4.0
    else:
        cauda = 0.0

    total = peso + lentidao + repeticao + cauda
    return round(min(100.0, total), 1), {
        "peso_periodo": round(peso, 1),
        "lentidao": round(lentidao, 1),
        "repeticao": round(repeticao, 1),
        "cauda": round(cauda, 1),
    }


def classe_de(pontuacao):
    if pontuacao >= 70:
        return "critica"
    if pontuacao >= 50:
        return "alta"
    if pontuacao >= 30:
        return "media"
    return "baixa"


# ------------------------------------------------------------------ bloco
def bloco_monitor(caminho, top=25):
    """Le o pacote do monitor e devolve o bloco `monitor` do evidencias.json."""
    fonte = FonteMonitor(caminho)
    consultas = fonte.achar("Monitor_Consulta")
    processos = fonte.achar("Monitor_Processos")
    if not consultas:
        return {"erro": "pacote sem Monitor_Consulta.log",
                "arquivos_no_pacote": fonte.nomes[:20]}

    pilhas, info_pilhas = ler_pilhas(fonte, processos) if processos else ({}, {"ids": 0, "truncado": False})
    r = varrer_consultas(fonte, consultas, pilhas)
    ag = r["ag"]
    tempo_total = r["tempo_total_ms"]

    itens = []
    for chave, item in ag.items():
        media = item.tempo_ms / item.execucoes if item.execucoes else 0
        p95 = _percentil(item.tempos, 0.95)
        pontuacao, parcelas = pontuar(item, tempo_total, p95)
        atencao = sorted(item.atencao)
        if (item.execucoes >= CORTE_N1_EXEC and media <= CORTE_N1_MEDIA_MS
                and item.comando == "SELECT"):
            atencao.append("suspeita_n_mais_1")
        itens.append({
            "impressao": chave,
            "sql": item.sql,
            "comando": item.comando,
            "objetos": item.objetos,
            "execucoes": item.execucoes,
            "tempo_total_ms": item.tempo_ms,
            "tempo_medio_ms": round(media, 1),
            "p95_ms": p95,
            "tempo_max_ms": item.maximo_ms,
            "pct_tempo_periodo": round(item.tempo_ms / tempo_total * 100, 2) if tempo_total else 0,
            "pontuacao": pontuacao,
            "classe": classe_de(pontuacao),
            "parcelas": parcelas,
            "atencao": [a for a in atencao if a in ATENCAO_CATALOGO],
            "requisicao_com_erro": "requisicao_com_erro" in item.atencao,
            "execucoes_com_erro": item.com_erro,
            "origens": [{"origem": k, "execucoes": v} for k, v in item.origens.most_common(3)],
            "aplicacoes": [{"aplicacao": k, "execucoes": v} for k, v in item.aplicacoes.most_common(3)],
            "ids_amostra": item.ids,
            "parametros_por_execucao": round(item.params / item.execucoes, 1) if item.execucoes else 0,
        })

    ofensivas = sorted(itens, key=lambda x: -x["pontuacao"])[:top]

    # --- erros: marcador no texto do bloco, e requisicao que terminou em erro
    erros = []
    for chave, item in ag.items():
        if not item.com_erro:
            continue
        for (marcador, linha), qtd in item.erros.most_common(3):
            erros.append({
                "impressao": chave,
                "marcador": marcador,
                "ocorrencias": qtd,
                "linha": linha,
                "sql": item.sql[:240],
                "comando": item.comando,
                "objetos": item.objetos,
                "origem": item.origens.most_common(1)[0][0] if item.origens else None,
            })
    erros.sort(key=lambda x: -x["ocorrencias"])

    # --- pontos de atencao agregados
    atencao_ag = defaultdict(lambda: {"consultas": 0, "execucoes": 0, "tempo_ms": 0,
                                      "exemplo": None})
    for x in itens:
        for rot in x["atencao"]:
            a = atencao_ag[rot]
            a["consultas"] += 1
            a["execucoes"] += x["execucoes"]
            a["tempo_ms"] += x["tempo_total_ms"]
            if a["exemplo"] is None or x["pontuacao"] > a["exemplo"]["pontuacao"]:
                a["exemplo"] = {"impressao": x["impressao"], "pontuacao": x["pontuacao"],
                                "sql": x["sql"][:160]}
    atencao = []
    contexto = []
    for rot, a in sorted(atencao_ag.items(), key=lambda kv: -kv[1]["tempo_ms"]):
        titulo, prova, nao_prova = ATENCAO_CATALOGO[rot]
        linha = {
            "rotulo": rot, "titulo": titulo,
            "consultas": a["consultas"], "execucoes": a["execucoes"],
            "tempo_ms": a["tempo_ms"],
            "o_que_mostra": prova, "o_que_nao_prova": nao_prova,
            "exemplo": a["exemplo"],
        }
        (contexto if rot in ATENCAO_CONTEXTO else atencao).append(linha)

    # --- origens
    por_origem = defaultdict(lambda: {"execucoes": 0, "tempo_ms": 0, "consultas": 0})
    for x in itens:
        for o in x["origens"]:
            d = por_origem[o["origem"]]
            d["execucoes"] += o["execucoes"]
            # rateio pela participacao daquela origem nas execucoes da consulta
            d["tempo_ms"] += int(x["tempo_total_ms"] * o["execucoes"] / max(x["execucoes"], 1))
            d["consultas"] += 1
    origens = [{"origem": k, **v,
                "tempo_medio_ms": round(v["tempo_ms"] / max(v["execucoes"], 1), 1)}
               for k, v in sorted(por_origem.items(), key=lambda kv: -kv[1]["tempo_ms"])[:20]]

    tempos = r["tempos"]
    faixas = [{"faixa": FAIXAS[i][0], "execucoes": r["faixas"][i], "tempo_ms": r["faixas_ms"][i],
               "pct_execucoes": round(r["faixas"][i] / max(r["capturadas"], 1) * 100, 1),
               "pct_tempo": round(r["faixas_ms"][i] / max(tempo_total, 1) * 100, 1)}
              for i in range(len(FAIXAS))]

    lentas = [x for x in itens if x["tempo_medio_ms"] >= CORTE_LENTA_MS]
    return {
        "pacote": os.path.abspath(caminho),
        "arquivos": r["arquivos"] + ([{"arquivo": n, "bytes": fonte.tamanho(n)}
                                      for n in processos] if processos else []),
        "tem_pilhas": bool(processos),
        "ids_com_pilha": info_pilhas["ids"],
        "truncado": info_pilhas["truncado"],
        "consultas_capturadas": r["capturadas"],
        "consultas_distintas": len(ag),
        "fingerprints_descartados": r["fingerprints_descartados"],
        "tempo_total_ms": tempo_total,
        "tempo_medio_ms": round(tempo_total / max(r["capturadas"], 1), 2),
        "p95_ms": _percentil(tempos, 0.95),
        "p99_ms": _percentil(tempos, 0.99),
        "maximo_ms": r["maximo_ms"],
        "acima_de_1s": sum(1 for t in tempos if t >= CORTE_LENTA_MS),
        "acima_de_5s": sum(1 for t in tempos if t >= CORTE_CAUDA_MS),
        "consultas_lentas": len(lentas),
        "faixas": faixas,
        "cobertura": r["cobertura"],
        "ofensivas": ofensivas,
        "por_origem": origens,
        "atencao": atencao,
        "contexto": contexto,
        "erros": erros[:25],
        "erros_total": sum(x["ocorrencias"] for x in erros),
        "requisicoes_com_erro": r["requisicoes_com_erro"],
        "sem_marcador_de_erro": not erros,
        "limiares": {
            "media_lenta_ms": CORTE_LENTA_MS,
            "cauda_ms": CORTE_CAUDA_MS,
            "n_mais_1_execucoes": CORTE_N1_EXEC,
            "n_mais_1_media_ms": CORTE_N1_MEDIA_MS,
            "faixas_pontuacao": {"critica": 70, "alta": 50, "media": 30},
        },
    }


# ------------------------------------------------------------------ resumo
def escrever_resumo(mon, caminho):
    L = ["# Resumo do Monitor de Consultas\n"]
    if mon.get("erro"):
        L.append(f"**{mon['erro']}**\n")
    else:
        L.append(f"Pacote: `{mon['pacote']}`\n")
        L.append(f"- {mon['consultas_capturadas']:,} execucoes capturadas · "
                 f"{mon['consultas_distintas']:,} consultas distintas"
                 + ("  (**truncado**)" if mon["truncado"] else ""))
        L.append(f"- tempo somado: {mon['tempo_total_ms']/1000:.1f} s · "
                 f"media {mon['tempo_medio_ms']} ms · p95 {mon['p95_ms']} ms · "
                 f"maximo {mon['maximo_ms']} ms")
        L.append(f"- acima de 1 s: {mon['acima_de_1s']} execucoes · "
                 f"acima de 5 s: {mon['acima_de_5s']}")
        cb = mon["cobertura"]
        L.append(f"- origem: {cb['com_runtime_info']} por Runtime-info, "
                 f"{cb['so_pilha']} so pela pilha, {cb['sem_origem']} sem origem")
        L.append("\n## Faixas de tempo\n")
        L.append("| faixa | execucoes | % exec | % do tempo |")
        L.append("|---|---:|---:|---:|")
        for f in mon["faixas"]:
            L.append(f"| {f['faixa']} | {f['execucoes']:,} | {f['pct_execucoes']}% | {f['pct_tempo']}% |")
        L.append("\n## Consultas ofensivas (top 10 por pontuacao)\n")
        L.append("| pont | classe | cmd | objetos | exec | media ms | max ms | % tempo | origem |")
        L.append("|---:|---|---|---|---:|---:|---:|---:|---|")
        for x in mon["ofensivas"][:10]:
            org = x["origens"][0]["origem"] if x["origens"] else "-"
            L.append(f"| {x['pontuacao']} | {x['classe']} | {x['comando']} | "
                     f"{','.join(x['objetos'][:2]) or '-'} | {x['execucoes']:,} | "
                     f"{x['tempo_medio_ms']} | {x['tempo_max_ms']} | "
                     f"{x['pct_tempo_periodo']}% | {org[:36]} |")
        if mon.get("contexto"):
            L.append("\n" + " · ".join(
                f"{c['titulo']}: {c['consultas']} consultas, {c['execucoes']:,} execucoes"
                for c in mon["contexto"]) + "  (contexto, nao apontamento)")
        if mon["atencao"]:
            L.append("\n## Pontos de atencao\n")
            L.append("| ponto | consultas | execucoes | tempo ms |")
            L.append("|---|---:|---:|---:|")
            for a in mon["atencao"]:
                L.append(f"| {a['titulo']} | {a['consultas']} | {a['execucoes']:,} | {a['tempo_ms']:,} |")
        L.append("\n## Erros\n")
        if mon["sem_marcador_de_erro"]:
            L.append("Nenhum marcador de erro no log do monitor deste pacote"
                     + (f"; {mon['requisicoes_com_erro']} execucoes partiram de requisicao "
                        f"que terminou em pagina de erro." if mon["requisicoes_com_erro"]
                        else "."))
        else:
            L.append("| marcador | ocorrencias | objetos | origem |")
            L.append("|---|---:|---|---|")
            for e in mon["erros"][:10]:
                L.append(f"| {e['marcador']} | {e['ocorrencias']} | "
                         f"{','.join(e['objetos'][:2]) or '-'} | {(e['origem'] or '-')[:36]} |")
        L.append("")
    with open(caminho, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description="Coleta o pacote do Monitor de Consultas.")
    ap.add_argument("--monitor", required=True, help="zip do monitor ou pasta extraida")
    ap.add_argument("--saida", default=".", help="pasta de saida")
    ap.add_argument("--top", type=int, default=25, help="quantas consultas no ranking")
    a = ap.parse_args()

    if not os.path.exists(a.monitor):
        print(f"Pacote nao encontrado: {a.monitor}", file=sys.stderr)
        return 2
    os.makedirs(a.saida, exist_ok=True)

    mon = bloco_monitor(a.monitor, top=a.top)
    p_json = os.path.join(a.saida, "monitor.json")
    p_md = os.path.join(a.saida, "monitor.md")
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump(mon, f, ensure_ascii=False, indent=1)
    escrever_resumo(mon, p_md)
    print(f"OK  {p_json}\nOK  {p_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
