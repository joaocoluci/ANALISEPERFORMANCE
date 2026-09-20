#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera os graficos do documento de Analise de Performance a partir do
evidencias.json produzido por coletar_metricas.py.

  python gerar_graficos.py --evidencias ./analise/evidencias.json --saida ./analise/graficos

Cada grafico ancora um argumento do texto. Grafico que nao sustenta uma frase do
documento nao entra: ilustracao sem tese e ruido caro de imprimir.

Requer matplotlib. Saida: PNG a 200 dpi, largura fixa compativel com a area util
do DOCX (15 cm).

--------------------------------------------------------------------- decisoes

PALETA. Brandbook Sankhya 2023, sem cor de fora. O validador de paletas reprova
este conjunto como paleta CATEGORICA (petroleo tem luminosidade 0,353, abaixo da
banda, e croma 0,04, que le como cinza). A resposta certa nao e inventar uma cor
vibrante fora da marca: e nao usar forma que precise de paleta categorica.

Todo grafico aqui e serie unica ou enfase (um destaque + contexto em cinza). Para
esse uso, o par medido pelo validador passa nas tres checagens que importam:

    CVD (protan/deutan/tritan)  DeltaE 24,8   PASS
    visao normal                DeltaE 25,5   PASS
    contraste vs superficie     >= 3:1        PASS

VERDE. #66CC66 tem contraste 1,97:1 sobre branco. Reprova como preenchimento de
area e some na impressao em preto e branco. Entra so como linha fina de
referencia, sempre acompanhada de rotulo em texto.

DOIS EIXOS. Nunca. Onde duas medidas de escalas diferentes precisam ser
comparadas (acessos e erros por hora), sao dois paineis empilhados com o mesmo
eixo x, nao duas escalas no mesmo plano.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from coletar_metricas import obter_serie  # noqa: E402

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

# ------------------------------------------------------------------ paleta
NAVY = "#2E3C50"     # destaque, serie principal
GREY = "#808285"     # contexto, referencia, serie secundaria
GREEN = "#66CC66"    # so linha de referencia, sempre com rotulo
GRID = "#EDEDED"     # grade, um tom acima da superficie
INK = "#2E3C50"      # titulo
LABEL = "#666666"    # eixos e rotulos secundarios
SURFACE = "#FFFFFF"

LARGURA_CM = 15.0
LARGURA_IN = LARGURA_CM / 2.54
DPI = 200

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Liberation Sans", "DejaVu Sans"],
    "font.size": 8.5,
    "axes.edgecolor": GRID,
    "axes.labelcolor": LABEL,
    "text.color": INK,
    "xtick.color": LABEL,
    "ytick.color": LABEL,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
})


def _base(ax, grid_eixo="y"):
    """Grade recessiva, sem moldura. Hairline solido, nunca tracejado."""
    ax.grid(axis=grid_eixo, color=GRID, linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(length=0)


def _titulo(ax, texto, sub=None):
    """Titulo e subtitulo em deslocamento absoluto (pontos), nao em fracao do
    eixo: a altura da figura varia com o numero de barras, e fracao faz o
    subtitulo colidir com o titulo nos graficos mais altos."""
    ax.annotate(texto, xy=(0, 1), xycoords="axes fraction",
                xytext=(0, 24 if sub else 9), textcoords="offset points",
                fontsize=10.5, fontweight="bold", color=INK, va="bottom", ha="left")
    if sub:
        ax.annotate(sub, xy=(0, 1), xycoords="axes fraction",
                    xytext=(0, 9), textcoords="offset points",
                    fontsize=8, color=LABEL, va="bottom", ha="left")


def _milhar(v, _=None):
    return f"{int(v):,}".replace(",", ".")


def _pct(v, _=None):
    return f"{v:.0f}%"


def _origem_curta(txt, limite=42):
    """Encurta `Classe.metodo` pelo LADO DA CLASSE.

    Cortar os ultimos 40 caracteres transformava
    `ComercioExteriorUtils.buscaParceiroFaturamento` em
    `ioExteriorUtils.buscaParceiroFaturamento`, que nao existe e manda o leitor
    procurar uma classe com esse nome.
    """
    if len(txt) <= limite:
        return txt
    if "." in txt:
        classe, metodo = txt.rsplit(".", 1)
        sobra = limite - len(metodo) - 2
        if sobra >= 6:
            return classe[:sobra] + "…." + metodo
        return "…" + metodo[-(limite - 1):]
    return txt[:limite - 1] + "…"


def _salvar(fig, caminho):
    fig.savefig(caminho, dpi=DPI, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)
    print("  " + os.path.basename(caminho))
    return caminho


# --------------------------------------------------- 1. carga x erro por hora
def carga_por_hora(ev, saida, base="."):
    """Dois paineis, mesmo eixo x. Nunca dois eixos y no mesmo plano: a
    sobreposicao de escalas inventa uma correlacao que o dado nao tem."""
    acessos = ev.get("acessos") or {}
    por_hora = obter_serie(ev, "logs", "por_hora", base)
    if not por_hora or not acessos.get("eventos_por_hora"):
        return None

    erros = {f"{h:02d}": 0 for h in range(24)}
    for x in por_hora:
        erros[x["hora"][11:13]] = erros.get(x["hora"][11:13], 0) + x["erros"]
    uso = {f"{h:02d}": 0 for h in range(24)}
    for x in acessos["eventos_por_hora"]:
        uso[x["hora"]] = x["eventos"]

    horas = [f"{h:02d}" for h in range(24)]
    v_uso = [uso[h] for h in horas]
    v_err = [erros[h] for h in horas]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(LARGURA_IN, 4.1), sharex=True)

    # painel 1: uso. Enfase nas horas de operacao, contexto no resto.
    cores = [NAVY if 7 <= int(h) <= 17 else GREY for h in horas]
    ax1.bar(horas, v_uso, color=cores, width=0.72, zorder=2)
    _base(ax1)
    _titulo(ax1, "Acessos de usuário por hora",
            "Barras escuras: horário de operação (7h às 17h)")
    ax1.yaxis.set_major_formatter(FuncFormatter(_milhar))
    pico = v_uso.index(max(v_uso))
    ax1.annotate(f"pico às {horas[pico]}h", xy=(pico, v_uso[pico]),
                 xytext=(0, 6), textcoords="offset points",
                 ha="center", fontsize=8, color=INK, fontweight="bold")

    # painel 2: erros, mesma janela destacada
    ax2.bar(horas, v_err, color=cores, width=0.72, zorder=2)
    _base(ax2)
    _titulo(ax2, "Eventos de erro por hora",
            "Acumulado do período, mesma faixa horária destacada")
    ax2.yaxis.set_major_formatter(FuncFormatter(_milhar))
    ax2.set_xlabel("hora do dia", fontsize=8, color=LABEL)

    fig.align_ylabels([ax1, ax2])
    fig.tight_layout(h_pad=2.2)
    return _salvar(fig, os.path.join(saida, "01-carga-por-hora.png"))


# ------------------------------------------------ 2. tempo medido x referencia
def dml_vs_referencia(ev, saida):
    """Barras agrupadas horizontais. Duas medidas da MESMA grandeza (ms), entao
    um eixo so resolve; nao e caso de dois eixos."""
    dml = ev.get("dml") or {}
    itens = [o for o in dml.get("objetos", []) if o.get("limite_ms")]
    if not itens:
        return None
    itens = sorted(itens, key=lambda o: -(o.get("excesso_pct") or 0))[:6]
    itens.reverse()

    rotulos = [f"{o['objeto']}  {o['operacao'].lower()}" for o in itens]
    medido = [o["tempo_medio_ms"] for o in itens]
    ref = [o["limite_ms"] for o in itens]

    y = range(len(itens))
    alt = 0.36
    fig, ax = plt.subplots(figsize=(LARGURA_IN, 0.50 * len(itens) + 1.3))
    ax.barh([i + alt / 2 for i in y], medido, height=alt, color=NAVY,
            label="Medido no período", zorder=2)
    ax.barh([i - alt / 2 for i in y], ref, height=alt, color=GREY,
            label="Referência Sankhya", zorder=2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(rotulos, fontsize=8.5, color=INK)
    _base(ax, grid_eixo="x")
    _titulo(ax, "Tempo médio por operação de banco",
            "Milissegundos por execução, contra a referência do checklist Sankhya")
    ax.xaxis.set_major_formatter(FuncFormatter(_milhar))

    # rotulo direto so na serie medida: numero em todo ponto vira ruido
    limite = max(medido) * 1.02
    for i, (m, o) in enumerate(zip(medido, itens)):
        exc = o.get("excesso_pct")
        txt = f"{_milhar(m)} ms" + (f"   {exc:+.0f}%" if exc is not None else "")
        ax.text(m + limite * 0.012, i + alt / 2, txt, va="center", fontsize=8,
                color=INK, fontweight="bold")
    ax.set_xlim(0, limite * 1.28)

    leg = ax.legend(loc="upper left", bbox_to_anchor=(0, -0.08), ncol=2,
                    frameon=False, fontsize=8.5, handlelength=1.1)
    for t in leg.get_texts():
        t.set_color(LABEL)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "02-dml-vs-referencia.png"))


# ------------------------------------------ 3. objetos mais custosos no periodo
def objetos_custosos(ev, saida, excluir=("STP_SET_SESSION2", "STP_SET_SESSION")):
    """Enfase: personalizados destacados, padrao em contexto. A identidade nao
    fica so na cor - a legenda nomeia os dois grupos e o eixo nomeia cada barra."""
    dml = ev.get("dml") or {}
    objs = [o for o in dml.get("objetos", []) if o["objeto"] not in excluir][:10]
    if not objs:
        return None
    objs.reverse()

    horas = [o["tempo_total_ms"] / 3_600_000 for o in objs]
    cores = [NAVY if o.get("personalizado") else GREY for o in objs]
    rotulos = [f"{o['objeto']}  {o['operacao'].lower()}" for o in objs]

    fig, ax = plt.subplots(figsize=(LARGURA_IN, 0.34 * len(objs) + 1.4))
    ax.barh(range(len(objs)), horas, color=cores, height=0.68, zorder=2)
    ax.set_yticks(range(len(objs)))
    ax.set_yticklabels(rotulos, fontsize=8, color=INK)
    _base(ax, grid_eixo="x")

    omitido = next((o for o in dml.get("objetos", []) if o["objeto"] in excluir), None)
    sub = "Horas de banco acumuladas no período"
    if omitido:
        h = omitido["tempo_total_ms"] / 3_600_000
        # nome tecnico fora do subtitulo: estoura a largura da area util
        sub += f". Abertura de sessão do sistema ({h:.0f} h) fora por escala"
    _titulo(ax, "Objetos de banco mais custosos", sub)

    for i, (h, o) in enumerate(zip(horas, objs)):
        ax.text(h + max(horas) * 0.012, i, f"{h:.1f} h  ·  {_milhar(o['execucoes'])} exec.",
                va="center", fontsize=7.5, color=LABEL)
    ax.set_xlim(0, max(horas) * 1.42)
    ax.set_xlabel("horas", fontsize=8, color=LABEL, labelpad=2)

    from matplotlib.patches import Patch
    leg = ax.legend(handles=[Patch(color=NAVY, label="Objeto personalizado"),
                             Patch(color=GREY, label="Objeto padrão do produto")],
                    loc="upper left", bbox_to_anchor=(0, -0.10), ncol=2,
                    frameon=False, fontsize=8.5, handlelength=1.1)
    for t in leg.get_texts():
        t.set_color(LABEL)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "03-objetos-custosos.png"))


# -------------------------------------------------------- 4. top de excecoes
def top_excecoes(ev, saida, marcadores=None, rotulo=None):
    """Assinaturas mais frequentes, com enfase opcional em uma familia.

    `marcadores` e `rotulo` vem da linha de comando (`--enfase-excecoes`,
    `--rotulo-excecoes`). Nao ha familia padrao: uma lista cravada no codigo
    ("mail", "SMTP") descrevia o incidente de UM cliente e reaparecia no
    documento de todos os outros, com subtitulo e legenda falando de e-mail onde
    o volume era de outra coisa.
    """
    exc = (ev.get("logs") or {}).get("excecoes") or []
    if not exc:
        return None
    itens = exc[:8][::-1]

    def curto(a):
        classe = a.split(":")[0].split(".")[-1]
        resto = a.split(":", 1)[1].strip() if ":" in a else ""
        return (classe + (f": {resto}" if resto else ""))[:52]

    valores = [e["ocorrencias"] for e in itens]
    if marcadores:
        familia = [any(m in e["assinatura"] for m in marcadores) for e in itens]
        cores = [NAVY if f else GREY for f in familia]
    else:
        cores = [NAVY] * len(itens)

    fig, ax = plt.subplots(figsize=(LARGURA_IN, 0.34 * len(itens) + 1.4))
    ax.barh(range(len(itens)), valores, color=cores, height=0.68, zorder=2)
    ax.set_yticks(range(len(itens)))
    ax.set_yticklabels([curto(e["assinatura"]) for e in itens], fontsize=7.5, color=INK)
    _base(ax, grid_eixo="x")
    sub = (f"Uma mesma falha gera mais de uma assinatura; em destaque: {rotulo}"
           if (marcadores and rotulo)
           else "Uma mesma falha costuma gerar mais de uma assinatura")
    _titulo(ax, "Exceções mais frequentes", sub)
    ax.xaxis.set_major_formatter(FuncFormatter(_milhar))
    for i, v in enumerate(valores):
        ax.text(v + max(valores) * 0.012, i, _milhar(v), va="center",
                fontsize=8, color=LABEL)
    ax.set_xlim(0, max(valores) * 1.2)

    if marcadores and rotulo:
        from matplotlib.patches import Patch
        leg = ax.legend(handles=[Patch(color=NAVY, label=rotulo[:40]),
                                 Patch(color=GREY, label="Outras assinaturas")],
                        loc="upper left", bbox_to_anchor=(0, -0.06), ncol=2,
                        frameon=False, fontsize=8.5, handlelength=1.1)
        for t in leg.get_texts():
            t.set_color(LABEL)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "04-excecoes.png"))


# ----------------------------------------------------------- 5. conexoes
def conexoes(ev, saida, base="."):
    """A tese do grafico e a planura: a serie nao acompanha a entrada dos
    usuarios, logo nao mede conexoes em uso."""
    conn = ev.get("conexoes") or {}
    porhora = conn.get("media_por_hora") or []
    if not porhora:
        return None

    horas = [p["hora"] for p in porhora]
    media = [p["media"] for p in porhora]
    maximo = [p["maximo"] for p in porhora]

    fig, ax = plt.subplots(figsize=(LARGURA_IN, 2.9))
    ax.plot(horas, maximo, color=GREY, linewidth=1.6, marker="o", markersize=3.2,
            label="Máximo observado", zorder=2)
    ax.plot(horas, media, color=NAVY, linewidth=2.0, marker="o", markersize=3.6,
            label="Média", zorder=3)

    ds = (ev.get("ambiente") or {}).get("datasource") or {}
    try:
        teto = int(ds.get("max_pool"))
    except (TypeError, ValueError):
        teto = None
    if teto:
        # verde so como linha de referencia, e sempre com rotulo em texto:
        # sozinho ele tem contraste 1,97:1 e desaparece na impressao P&B
        ax.axhline(teto, color=GREEN, linewidth=1.8, zorder=1)
        ax.text(len(horas) - 0.4, teto, f"  pool configurado: {teto}",
                fontsize=8, color=LABEL, va="bottom", ha="right")

    _base(ax)
    _titulo(ax, "Conexões por hora do dia",
            "Média das amostras de 5 em 5 minutos, ao longo do período")
    ax.set_xlabel("hora do dia", fontsize=8, color=LABEL)
    ax.set_ylim(0, max(maximo) * 1.22)
    # legenda fora da area de plotagem: dentro dela, "Media" cai exatamente sobre
    # a serie da media quando a serie e chapada e baixa
    leg = ax.legend(loc="upper left", bbox_to_anchor=(0, -0.16), ncol=2,
                    frameon=False, fontsize=8.5, handlelength=1.6)
    for t in leg.get_texts():
        t.set_color(LABEL)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "05-conexoes.png"))


# ------------------------------------------------------- 6. erros no periodo
def erros_no_periodo(ev, saida, base="."):
    """Serie unica ao longo do tempo: mostra se o problema e continuo ou pontual."""
    porhora = obter_serie(ev, "logs", "por_hora", base)
    if not porhora:
        return None
    dias = {}
    for x in porhora:
        dias[x["hora"][:10]] = dias.get(x["hora"][:10], 0) + x["erros"]
    if len(dias) < 3:
        return None
    chaves = sorted(dias)
    valores = [dias[k] for k in chaves]

    fig, ax = plt.subplots(figsize=(LARGURA_IN, 2.6))
    ax.fill_between(range(len(chaves)), valores, color=NAVY, alpha=0.10, zorder=1)
    ax.plot(range(len(chaves)), valores, color=NAVY, linewidth=1.5, zorder=2)
    _base(ax)
    _titulo(ax, "Eventos de erro por dia",
            "Todo o período coberto pelo pacote de log")
    ax.yaxis.set_major_formatter(FuncFormatter(_milhar))

    # rotula so o extremo: valor em todo ponto e ruido
    pico = valores.index(max(valores))
    ax.annotate(f"{_milhar(valores[pico])} em {chaves[pico][8:10]}/{chaves[pico][5:7]}",
                xy=(pico, valores[pico]), xytext=(0, 7), textcoords="offset points",
                ha="center", fontsize=8, color=INK, fontweight="bold")

    passo = max(1, len(chaves) // 8)
    ax.set_xticks(range(0, len(chaves), passo))
    ax.set_xticklabels([f"{chaves[i][8:10]}/{chaves[i][5:7]}"
                        for i in range(0, len(chaves), passo)], fontsize=8)
    ax.set_ylim(0, max(valores) * 1.18)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "06-erros-por-dia.png"))


# ------------------------------------------- 7. pontuacao das consultas
def monitor_pontuacao(ev, saida):
    """Enfase por faixa: o que passou de 50 pontos contra o resto.

    Nao empilhar as quatro parcelas da pontuacao numa barra: quatro segmentos
    exigem paleta categorica, e a paleta da marca reprova nessa forma. As
    parcelas moram no `evidencias.json` e entram no texto, nao no desenho.
    """
    mon = ev.get("monitor") or {}
    itens = (mon.get("ofensivas") or [])[:10]
    if not itens:
        return None
    itens = itens[::-1]

    def rotulo(x):
        obj = ",".join(x["objetos"][:2]) or x["comando"]
        return f"{obj[:26]}  ({x['comando'].lower()})"

    valores = [x["pontuacao"] for x in itens]
    graves = [x["classe"] in ("critica", "alta") for x in itens]
    cores = [NAVY if g else GREY for g in graves]

    fig, ax = plt.subplots(figsize=(LARGURA_IN, 0.36 * len(itens) + 1.5))
    ax.barh(range(len(itens)), valores, color=cores, height=0.68, zorder=2)
    ax.set_yticks(range(len(itens)))
    ax.set_yticklabels([rotulo(x) for x in itens], fontsize=8, color=INK)
    _base(ax, grid_eixo="x")
    _titulo(ax, "Pontuação de ofensa por consulta",
            "Soma de peso no período, lentidão unitária, repetição e cauda (0 a 100)")

    # verde so como linha de referencia, e sempre com rotulo em texto
    # zorder abaixo das barras: `set_axisbelow` empurra a grade para 0,5 e uma
    # linha em zorder 1 acaba desenhada SOBRE a barra escura
    ax.axvline(50, color=GREEN, linewidth=1.8, zorder=0.4)
    # rotulo a esquerda da linha: a direita ele encosta na margem da area util
    ax.text(50, len(itens) - 0.4, "faixa alta (50 pontos)  ", fontsize=8,
            color=LABEL, va="top", ha="right")

    for i, (v, x) in enumerate(zip(valores, itens)):
        ax.text(v + 1.2, i, f"{v:.0f}  ·  {_milhar(x['execucoes'])} exec.  ·  "
                            f"{x['tempo_medio_ms']:.0f} ms",
                va="center", fontsize=7.5, color=LABEL)
    ax.set_xlim(0, max(max(valores) * 1.55, 60))

    from matplotlib.patches import Patch
    leg = ax.legend(handles=[Patch(color=NAVY, label="Pontuação alta ou crítica"),
                             Patch(color=GREY, label="Abaixo da faixa de atenção")],
                    loc="upper left", bbox_to_anchor=(0, -0.08), ncol=2,
                    frameon=False, fontsize=8.5, handlelength=1.1)
    for t in leg.get_texts():
        t.set_color(LABEL)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "07-monitor-pontuacao.png"))


# ------------------------------------------- 8. faixas de tempo do monitor
def monitor_faixas(ev, saida):
    """Dois paineis, mesma unidade (%): a tese e a desproporcao entre quantas
    execucoes caem em cada faixa e quanto tempo cada faixa consome."""
    mon = ev.get("monitor") or {}
    faixas = mon.get("faixas") or []
    if not faixas or not mon.get("consultas_capturadas"):
        return None

    rotulos = [f["faixa"] for f in faixas]
    exec_pct = [f["pct_execucoes"] for f in faixas]
    tempo_pct = [f["pct_tempo"] for f in faixas]
    lentas = [i for i, f in enumerate(faixas) if "1 s" in f["faixa"] or "5 s" in f["faixa"]]
    cores = [NAVY if i in lentas else GREY for i in range(len(faixas))]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(LARGURA_IN, 3.9), sharex=True)
    ax1.bar(rotulos, exec_pct, color=cores, width=0.62, zorder=2)
    _base(ax1)
    ax1.yaxis.set_major_formatter(FuncFormatter(_pct))
    _titulo(ax1, "Distribuição das execuções por faixa de tempo",
            "Percentual das execuções capturadas pelo Monitor de Consultas")
    for i, v in enumerate(exec_pct):
        ax1.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=8, color=LABEL)
    ax1.set_ylim(0, max(exec_pct) * 1.20)

    ax2.bar(rotulos, tempo_pct, color=cores, width=0.62, zorder=2)
    _base(ax2)
    ax2.yaxis.set_major_formatter(FuncFormatter(_pct))
    _titulo(ax2, "Participação de cada faixa no tempo total",
            "Barras escuras: execuções acima de 1 segundo")
    for i, v in enumerate(tempo_pct):
        ax2.text(i, v, f"{v:.1f}%", ha="center", va="bottom", fontsize=8, color=LABEL)
    ax2.set_ylim(0, max(tempo_pct) * 1.20)

    fig.align_ylabels([ax1, ax2])
    fig.tight_layout(h_pad=2.4)
    return _salvar(fig, os.path.join(saida, "08-monitor-faixas.png"))


# ----------------------------------------------- 9. origem das consultas
def monitor_origens(ev, saida):
    """Quem chamou, por tempo acumulado. Responde a quem encaminhar o ajuste."""
    mon = ev.get("monitor") or {}
    itens = (mon.get("por_origem") or [])[:8]
    if not itens:
        return None
    itens = itens[::-1]

    segundos = [x["tempo_ms"] / 1000.0 for x in itens]
    fig, ax = plt.subplots(figsize=(LARGURA_IN, 0.36 * len(itens) + 1.3))
    ax.barh(range(len(itens)), segundos, color=NAVY, height=0.68, zorder=2)
    ax.set_yticks(range(len(itens)))
    ax.set_yticklabels([_origem_curta(x["origem"]) for x in itens],
                       fontsize=7.5, color=INK)
    _base(ax, grid_eixo="x")
    _titulo(ax, "Tempo de banco por origem da chamada",
            "Runtime-info quando o bloco a traz; caso contrário, o primeiro método "
            "de negócio da pilha")
    for i, (s, x) in enumerate(zip(segundos, itens)):
        ax.text(s + max(segundos) * 0.012, i,
                f"{s:.1f} s  ·  {_milhar(x['execucoes'])} exec.",
                va="center", fontsize=7.5, color=LABEL)
    ax.set_xlim(0, max(segundos) * 1.40)
    ax.set_xlabel("segundos", fontsize=8, color=LABEL, labelpad=2)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "09-monitor-origens.png"))


# ------------------------------------------------ 10. consultas com erro
def monitor_erros(ev, saida):
    """So sai quando existe erro. Pacote sem erro nao ganha grafico vazio: a
    ausencia entra no texto, com essas palavras."""
    mon = ev.get("monitor") or {}
    erros = mon.get("erros") or []
    total = sum(e["ocorrencias"] for e in erros)
    # Uma barra com uma ocorrencia nao e grafico: a tabela diz o mesmo em menos
    # espaco e sem sugerir volume. Abaixo destes cortes, so o texto.
    if len(erros) < 3 and total < 10:
        return None
    itens = erros[:8][::-1]
    valores = [e["ocorrencias"] for e in itens]

    def rotulo(e):
        obj = ",".join(e["objetos"][:2]) or e["comando"]
        return f"{e['marcador']}  {obj[:22]}"

    fig, ax = plt.subplots(figsize=(LARGURA_IN, 0.36 * len(itens) + 1.3))
    ax.barh(range(len(itens)), valores, color=NAVY, height=0.68, zorder=2)
    ax.set_yticks(range(len(itens)))
    ax.set_yticklabels([rotulo(e) for e in itens], fontsize=7.5, color=INK)
    _base(ax, grid_eixo="x")
    _titulo(ax, "Consultas com erro no Monitor de Consultas",
            "Ocorrências por marcador de erro e objeto envolvido")
    # contagem e inteira: sem isto o eixo repete "0 0 0 0 1" quando o maximo e 1
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_major_formatter(FuncFormatter(_milhar))
    for i, v in enumerate(valores):
        ax.text(v + max(valores) * 0.012, i, _milhar(v), va="center",
                fontsize=8, color=LABEL)
    ax.set_xlim(0, max(valores) * 1.22)
    fig.tight_layout()
    return _salvar(fig, os.path.join(saida, "10-monitor-erros.png"))


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Gera os graficos do documento.")
    ap.add_argument("--evidencias", required=True)
    ap.add_argument("--saida", required=True)
    ap.add_argument("--enfase-excecoes", default=None,
                    help="trechos separados por vírgula que identificam a família de "
                         "exceções a destacar no gráfico 04")
    ap.add_argument("--rotulo-excecoes", default=None,
                    help="nome da família destacada, para legenda e subtítulo")
    args = ap.parse_args()

    with open(args.evidencias, encoding="utf-8") as f:
        ev = json.load(f)
    os.makedirs(args.saida, exist_ok=True)

    print("gerando graficos:")
    feitos = []
    base = os.path.dirname(os.path.abspath(args.evidencias))
    for fn in (carga_por_hora, dml_vs_referencia, objetos_custosos,
               top_excecoes, conexoes, erros_no_periodo,
               monitor_pontuacao, monitor_faixas, monitor_origens, monitor_erros):
        try:
            # so as funcoes de serie temporal precisam do diretorio base
            if fn in (carga_por_hora, conexoes, erros_no_periodo):
                r = fn(ev, args.saida, base)
            elif fn is top_excecoes:
                marcadores = ([m.strip() for m in args.enfase_excecoes.split(",")]
                              if args.enfase_excecoes else None)
                r = fn(ev, args.saida, marcadores, args.rotulo_excecoes)
            else:
                r = fn(ev, args.saida)
            if r:
                feitos.append(r)
            else:
                print(f"  (sem dado para {fn.__name__})")
        except Exception as e:
            print(f"  FALHOU {fn.__name__}: {type(e).__name__}: {e}", file=sys.stderr)

    print(f"\n{len(feitos)} grafico(s) em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
