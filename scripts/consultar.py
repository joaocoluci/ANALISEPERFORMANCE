#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta pontual ao evidencias.json, em texto compacto.

Existe para evitar o `Read` do JSON inteiro. Mesmo depois de separar as series
densas, o arquivo tem ~39 mil tokens; cada recorte daqui custa algumas centenas.

  python consultar.py --evidencias ./analise/evidencias.json --o tudo
  python consultar.py --evidencias ./analise/evidencias.json --o dml --n 15
  python consultar.py --evidencias ./analise/evidencias.json --o achados --sev alta
  python consultar.py --evidencias ./analise/evidencias.json --o excecoes --verbose

`--o tudo` imprime os treze recortes essenciais numa chamada, por ~3 mil tokens.
Comece por ele: pedir um a um custa uma ida e volta por recorte.

Essenciais:  diagnostico ambiente banco achados ciclo cpu sinais excecoes
             oracle dml conexoes acessos hora
Sob demanda: args (secao 8) · wildfly drivers (secao 9) · secoes threads jobs
             monitor monitor-atencao monitor-erros monitor-origens
"""

import argparse
import json
import re
import sys


def _t(v, n=90):
    s = str(v).replace("\n", " ")
    return s[:n]


def _num(v):
    try:
        return f"{int(v):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(v)


def secoes(ev, a):
    """Mapa do arquivo: o que existe e quanto pesa, sem despejar conteudo."""
    print("bloco             itens  peso")
    for k in ev:
        v = ev[k]
        n = len(v) if isinstance(v, (list, dict)) else 1
        kb = len(json.dumps(v, ensure_ascii=False)) / 1024
        print(f"  {k:16} {n:5}  {kb:7.1f} KB")
    m = ev.get("meta", {})
    print(f"\npacote: {m.get('pacote','?')}")
    print(f"modo: {m.get('modo')} · {m.get('duracao_s')}s · séries em {m.get('series_em','(no próprio arquivo)')}")


def ambiente(ev, a):
    amb = ev.get("ambiente") or {}
    for k in ("empresa", "versao_sankhyaw", "versao_servidor", "java", "jvm",
              "sistema_operacional", "memoria_heap", "heap_uso_pct", "xms_mb",
              "xmx_mb", "gc", "encoding_arquivo"):
        if amb.get(k) is not None:
            print(f"{k:22} {_t(amb[k], 110)}")
    ds = amb.get("datasource") or {}
    if ds:
        print(f"{'datasource':22} driver={ds.get('driver')} pool={ds.get('min_pool')}/{ds.get('max_pool')}")
    mods = amb.get("modulos") or {}
    if mods:
        print(f"{'modulos':22} " + ", ".join(f"{k}={v}" for k, v in list(mods.items())[:12]))


def achados(ev, a):
    itens = ev.get("achados") or []
    if a.sev:
        itens = [x for x in itens if x["severidade"] == a.sev]
    for x in itens[: a.n]:
        print(f"[{x['severidade']:8}] {x['titulo']}")
        print(f"            {_t(x['evidencia'], 150)}")
        if a.verbose:
            print(f"            fonte: {x['fonte']}")
            print(f"            ação:  {_t(x['recomendacao'], 200)}")


def dml(ev, a):
    d = ev.get("dml") or {}
    print(f"{'objeto':30}{'op':9}{'exec':>12}{'total ms':>13}{'média':>9}{'limite':>8}{'exc%':>8}  perso")
    for o in (d.get("objetos") or [])[: a.n]:
        exc = f"{o['excesso_pct']:+.0f}" if o.get("excesso_pct") is not None else ""
        print(f"{o['objeto'][:29]:30}{o['operacao']:9}{_num(o['execucoes']):>12}"
              f"{_num(o['tempo_total_ms']):>13}{o['tempo_medio_ms']:>9.1f}"
              f"{str(o.get('limite_ms') or ''):>8}{exc:>8}  {'sim' if o['personalizado'] else ''}")
    v = d.get("violacoes_limite") or []
    if v:
        print(f"\n{len(v)} acima do limite: " + ", ".join(f"{o['objeto']}/{o['operacao']}" for o in v))


def excecoes(ev, a):
    for e in ((ev.get("logs") or {}).get("excecoes") or [])[: a.n]:
        print(f"{_num(e['ocorrencias']):>10}  {_t(e['assinatura'], 100)}")
        print(f"{'':10}  {e['primeira']} a {e['ultima']}")
        if a.verbose and e.get("amostra"):
            print(f"{'':10}  {_t(e['amostra'], 200)}")


def oracle(ev, a):
    for o in ((ev.get("logs") or {}).get("oracle") or [])[: a.n]:
        print(f"{o['codigo']:12}{_num(o['ocorrencias']):>10}  {_t(o.get('significado') or '', 90)}")


def sinais(ev, a):
    lg = ev.get("logs") or {}
    for k, v in sorted((lg.get("sinais") or {}).items(), key=lambda x: -x[1]):
        print(f"{k:20}{_num(v):>10}")
    if a.verbose:
        for k, amostras in (lg.get("sinais_amostra") or {}).items():
            for x in amostras[:1]:
                print(f"\n{k}: {x.get('quando')}\n  {_t(x['linha'], 180)}")


def jobs(ev, a):
    print(f"{'job':52}{'exec':>8}{'total ms':>12}{'média':>9}{'máx':>9}")
    for j in ((ev.get("logs") or {}).get("jobs") or [])[: a.n]:
        print(f"{_t(j['job'], 51):52}{j['execucoes']:>8}{_num(j['tempo_total_ms']):>12}"
              f"{j['tempo_medio_ms']:>9.1f}{_num(j['tempo_max_ms']):>9}")


def conexoes(ev, a):
    c = ev.get("conexoes") or {}
    if not c:
        return
    print(f"amostras {c['amostras']} · média {c['media']} · p95 {c['p95']} · "
          f"máx {c['maximo']} em {c['pico']['quando']}")
    print("\nhora   média    máx")
    for h in c.get("media_por_hora") or []:
        print(f"  {h['hora']}  {h['media']:7.1f} {h['maximo']:6}")


def threads(ev, a):
    t = ev.get("threads_dump") or {}
    if not t:
        return
    print(f"{t['total']} threads em {t['gerado_em']} · {t['por_estado']}")
    if t.get("bloqueadas"):
        print(f"\nbloqueadas ({len(t['bloqueadas'])}):")
        for b in t["bloqueadas"][:10]:
            print(f"  {_t(b['nome'], 40):42} {_t(b.get('topo') or '', 70)}")
    print("\ntop cpu:")
    for x in (t.get("top_cpu") or [])[:8]:
        print(f"  {x['cpu_ms']:>10} ms  {_t(x['nome'], 38):40} {_t(x.get('topo_pilha') or '', 60)}")


def acessos(ev, a):
    ac = ev.get("acessos") or {}
    if not ac:
        return
    print(f"{_num(ac['eventos'])} eventos · {ac['dias']} dias · {ac['sessoes_distintas']} sessões")
    for rot in ("top_telas", "top_servicos", "top_usuarios"):
        if ac.get(rot):
            print(f"\n{rot}:")
            for x in ac[rot][: a.n]:
                print(f"  {_num(x['ocorrencias']):>8}  {_t(x['chave'], 70)}")


def wildfly(ev, a):
    w = ev.get("wildfly") or {}
    if not w or w.get("erro"):
        print(w.get("erro", "sem dados"))
        return
    print(f"cliente {w['versao_cliente']} · referência {w['baseline']['versao']}"
          + ("  <- desatualizado" if w.get("desatualizado") else ""))
    if w.get("banco"):
        print(f"banco: {w['banco'][0]['banner']}")
    for rot in ("ausentes", "divergentes", "dimensionamento", "extras", "ausentes_condicionais"):
        itens = w.get(rot) or []
        if itens:
            print(f"\n{rot} ({len(itens)}):")
            for x in itens:
                extra = x.get("valor_cliente") or x.get("valor_referencia") or ""
                motivo = f"   ({x['motivo']})" if x.get("motivo") else ""
                print(f"  {x['argumento']:48} {_t(extra, 40)}{motivo}")


def args_vm(ev, a):
    for x in ((ev.get("wildfly") or {}).get("argumentos_cliente") or []):
        print(f"{x['argumento']:52} {_t(x['valor'] or '', 60)}")


def drivers(ev, a):
    w = ev.get("wildfly") or {}
    for d in w.get("drivers") or []:
        sit = ("descontinuado" if d.get("descontinuado")
               else "atrasado" if d.get("atrasado") else "em dia")
        print(f"{d['classe']:48} {d['versao_cliente']:>10} vs {str(d['versao_referencia'] or '-'):>12}  {sit}")
    inv = w.get("drivers_invalidos") or []
    if inv:
        print("\nJAR não resolvido: " + ", ".join(f"{x['jar']} ({x['ocorrencias']}x)" for x in inv))


def diagnostico(ev, a):
    """Bloco de diagnostico do proprio pacote: valor medido e limite recomendado.

    E o recorte mais barato com maior poder de desmentir achado automatico. Ler
    este antes dos `achados` evita reportar pressao de memoria onde o GC gasta
    0,09%, e evita analisar lentidao de producao sobre pacote de teste.
    """
    d = ev.get("diagnostico") or {}
    if not d:
        print("sem bloco de diagnostico no comentario deste pacote")
        return
    if d.get("estereotipo"):
        marca = "PRODUÇÃO" if d.get("producao") else "NÃO É PRODUÇÃO"
        print(f"base: {d['estereotipo']}  ({marca})")
    if d.get("host"):
        print(f"host: {d['host']}")
    if d.get("dd_data_importacao"):
        print(f"dicionário importado em: {d['dd_data_importacao']}")
    print()
    for x in d.get("itens", []):
        rec = f"  |  recomendado: {x['recomendado']}" if x.get("recomendado") else ""
        print(f"  {x['item']:34} {_t(x['valor'], 42):42}{rec}")
    if d.get("triggers_pendentes"):
        print("\n  ATENÇÃO: há pendência de trigger desabilitada na base.")
    pp = d.get("parametros_performance") or {}
    if pp and a.verbose:
        print("\nparâmetros de performance:")
        for k, v in pp.items():
            print(f"  {k:24} {v}")


def ciclo(ev, a):
    """Subida do servidor, servicos falhos, republicacoes e falhas de migracao."""
    c = ((ev.get("logs") or {}).get("ciclo_de_vida")) or {}
    if not c:
        print("sem bloco de ciclo de vida (recoletar com a versão atual do coletor)")
        return
    for b in c.get("boots", []):
        erro = "  COM ERROS" if b.get("com_erros") else ""
        serv = (f"  {b['servicos_iniciados']} de {b['servicos_total']} serviços"
                if b.get("servicos_total") else "")
        # falhos vem declarado pelo servidor; a diferenca com o total sao os
        # servicos sob demanda, que nao falharam
        falhos = (f" ({b['servicos_falhos']} falhos)"
                  if b.get("servicos_falhos") else "")
        print(f"subida {b.get('quando') or '?'}  {b['tempo_ms'] / 1000:.0f}s{erro}{serv}{falhos}")

    sf = c.get("servicos_falhos") or []
    if sf:
        print(f"\nserviços que não subiram ({len(sf)} distintos):")
        for x in sf[: a.n]:
            print(f"  {x['ocorrencias']:4}x  {_t(x['servico'], 68)}")

    if c.get("redeploys_total"):
        dias = ", ".join(f"{x['dia']}: {x['republicacoes']}"
                         for x in c.get("redeploys_por_dia", []))
        print(f"\nrepublicações de módulo: {c['redeploys_total']}  ({dias})")
        for x in (c.get("redeploys_por_modulo") or [])[:8]:
            print(f"  {x['republicacoes']:4}x  {x['modulo']}")

    if c.get("threads_nao_encerradas_total"):
        dias = ", ".join(f"{x['dia']}: {x['falhas']}"
                         for x in c.get("threads_nao_encerradas_por_dia", []))
        print(f"\nthreads não encerradas na republicação: "
              f"{c['threads_nao_encerradas_total']}  ({dias})")

    if c.get("migracao_falhas_total"):
        print(f"\nfalhas de script de migração: {c['migracao_falhas_total']}")
        for x in (c.get("migracao_falhas_por_modulo") or [])[: a.n]:
            print(f"  {x['falhas']:5}  {x['modulo']}")


def cpu(ev, a):
    """CPU acumulada por familia de thread, com o denominador correto.

    Dois denominadores, e confundi-los muda a conclusao: `pct_vivas` e sobre as
    threads presentes no dump; `pct_processo` e sobre a CPU que o processo
    consumiu desde que subiu, que so existe quando o pacote traz o diagnostico.
    """
    t = ev.get("threads_dump") or {}
    f = (t.get("cpu_por_familia") or {})
    if not f:
        print("sem agregação de CPU (recoletar com a versão atual do coletor)")
        return
    d = ev.get("diagnostico") or {}
    itens = d.get("itens", [])
    cpu_txt = next((x["valor"] for x in itens
                    if x["item"].lower().startswith("tempo de cpu utilizado")), None)
    seg_proc = None
    if cpu_txt:
        m = re.search(r"\[(\d+):(\d\d):(\d\d)\s*/", cpu_txt)
        if m:
            seg_proc = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))

    print(f"dump de {t.get('gerado_em') or '?'} · {t.get('analisadas')} threads vivas "
          f"· {f['familias'][0]['cpu_ms'] and t['cpu_ms_total_vivas'] / 1000:.0f}s de CPU somada")
    if seg_proc:
        print(f"CPU do processo desde a subida: {seg_proc}s ({cpu_txt})")
    print()
    cab = "     cpu  %vivas" + ("  %proc" if seg_proc else "") + "  thr  família"
    print(cab)
    for x in f["familias"]:
        pp = f"  {x['cpu_ms'] / 10 / seg_proc:5.2f}%" if seg_proc else ""
        print(f"  {x['cpu_ms'] / 1000:6.0f}s  {x['pct_das_vivas']:6.2f}%{pp}"
              f"  {x['threads']:3d}  {x['familia']}")
    if a.verbose:
        print(f"\n{f['ressalva']}")


def banco(ev, a):
    """Dialeto do banco em uso e os scripts que podem ser entregues ao cliente.

    O `--verbose` acrescenta a pergunta que cada script responde. Sem ele, a
    saida cabe em poucas linhas e ja diz o que precisa entrar na secao 12.
    """
    b = ev.get("banco") or {}
    if not b:
        print("sem bloco de banco nesta coleta (recoletar com a versao atual do coletor)")
        return
    if b.get("dialeto"):
        print(f"{b['nome']}" + (f" {b['versao']}" if b.get("versao") else ""))
        print(f"detectado por: {b['fonte']}")
        print(f"evidência:     {b['evidencia']}")
        if b.get("banner"):
            print(f"banner:        {_t(b['banner'], 80)}")
    else:
        print("DIALETO NÃO IDENTIFICADO — nenhum script pode ser entregue ao cliente.")
        print("Sem URL de datasource, banner no log ou driver único, o pacote não")
        print("responde qual banco está em uso.")

    if b.get("conflito"):
        c = b["conflito"]
        print(f"\nFONTES DISCORDAM: URL diz {c['url']['dialeto']}, "
              f"banner diz {c['banner']['dialeto']}")
        print(f"  {c['leitura']}")

    carregados = b.get("drivers_carregados") or []
    if len(carregados) > 1:
        print(f"\ndrivers carregados de mais de um dialeto: {', '.join(carregados)}")
        print("  driver carregado não decide o banco em uso")

    s = b.get("scripts") or {}
    if s.get("erro"):
        print(f"\n{s['erro']}")
        return
    if s.get("aplicaveis"):
        print(f"\naplicáveis ({len(s['aplicaveis'])}):")
        for x in s["aplicaveis"]:
            aviso = "  [altera estrutura]" if x["tipo"] in ("ddl", "objeto") else ""
            autoral = "  [autoral]" if x.get("origem") == "skill" else ""
            print(f"  {x['id']:24} {x['arquivo']:36}{aviso}{autoral}")
            if x.get("dependencia"):
                print(f"  {'':24} depende de {x['dependencia']}")
            if a.verbose:
                print(f"  {'':24} {_t(x['pergunta'], 70)}")
    if s.get("lacunas"):
        print(f"\nsem script para este dialeto ({len(s['lacunas'])}):")
        for x in s["lacunas"]:
            print(f"  {x['id']:24} {_t(x['motivo'], 66)}")


def monitor(ev, a):
    """Ranking de consultas ofensivas do Monitor de Consultas."""
    m = ev.get("monitor") or {}
    if not m:
        print("sem pacote do monitor nesta coleta")
        return
    if m.get("erro"):
        print(m["erro"])
        return
    print(f"{_num(m['consultas_capturadas'])} execuções · "
          f"{_num(m['consultas_distintas'])} consultas distintas · "
          f"tempo somado {m['tempo_total_ms']/1000:.1f} s"
          + ("  (TRUNCADO)" if m.get("truncado") else ""))
    print(f"média {m['tempo_medio_ms']} ms · p95 {m['p95_ms']} · p99 {m['p99_ms']} · "
          f"máx {m['maximo_ms']} ms · acima de 1 s: {m['acima_de_1s']} · "
          f"acima de 5 s: {m['acima_de_5s']}")
    cb = m.get("cobertura") or {}
    print(f"origem: {cb.get('com_runtime_info', 0)} Runtime-info · "
          f"{cb.get('so_pilha', 0)} pilha · {cb.get('sem_origem', 0)} sem origem")
    print("\nfaixa            execuções   % exec   % tempo")
    for f in m.get("faixas", []):
        print(f"  {f['faixa']:15}{_num(f['execucoes']):>8}{f['pct_execucoes']:>8}%"
              f"{f['pct_tempo']:>9}%")
    print(f"\n{'pont':>5} {'classe':8} {'cmd':7} {'objetos':22}{'exec':>8}{'média':>8}"
          f"{'máx':>8}{'%tempo':>8}  origem")
    for x in m.get("ofensivas", [])[: a.n]:
        org = x["origens"][0]["origem"] if x["origens"] else "-"
        print(f"{x['pontuacao']:>5} {x['classe']:8} {x['comando']:7} "
              f"{','.join(x['objetos'][:2])[:21]:22}{_num(x['execucoes']):>8}"
              f"{x['tempo_medio_ms']:>8.1f}{_num(x['tempo_max_ms']):>8}"
              f"{x['pct_tempo_periodo']:>7.1f}%  {_t(org, 34)}")
        if a.verbose:
            p = x["parcelas"]
            print(f"      peso {p['peso_periodo']} · lentidão {p['lentidao']} · "
                  f"repetição {p['repeticao']} · cauda {p['cauda']}"
                  + (f" · atenção: {', '.join(x['atencao'])}" if x["atencao"] else ""))
            print(f"      {_t(x['sql'], 200)}")


def monitor_atencao(ev, a):
    """Pontos de atencao e, em cada um, o que a evidencia nao prova."""
    m = ev.get("monitor") or {}
    for rot in ("atencao", "contexto"):
        itens = m.get(rot) or []
        if not itens:
            continue
        print(("PONTOS DE ATENÇÃO" if rot == "atencao"
               else "CONTEXTO (não é apontamento)"))
        for x in itens[: a.n]:
            print(f"  {x['titulo']}  —  {x['consultas']} consultas · "
                  f"{_num(x['execucoes'])} execuções · {_num(x['tempo_ms'])} ms")
            print(f"      mostra:    {_t(x['o_que_mostra'], 140)}")
            print(f"      não prova: {_t(x['o_que_nao_prova'], 140)}")
            if a.verbose and x.get("exemplo"):
                print(f"      exemplo ({x['exemplo']['pontuacao']} pts): "
                      f"{_t(x['exemplo']['sql'], 130)}")
        print()


def monitor_erros(ev, a):
    """Consultas com erro. Zero erro tambem e resultado, e vai dito assim."""
    m = ev.get("monitor") or {}
    if not m:
        print("sem pacote do monitor nesta coleta")
        return
    if m.get("sem_marcador_de_erro"):
        print("nenhum marcador de erro no log do monitor deste pacote")
    else:
        print(f"{'marcador':34}{'ocorr.':>8}  objetos / origem")
        for e in (m.get("erros") or [])[: a.n]:
            print(f"{_t(e['marcador'], 33):34}{e['ocorrencias']:>8}  "
                  f"{','.join(e['objetos'][:2]) or '-'} / {_t(e.get('origem') or '-', 40)}")
            print(f"{'':34}{'':8}  {_t(e['linha'], 130)}")
            if a.verbose:
                print(f"{'':34}{'':8}  {_t(e['sql'], 180)}")
    print(f"\nexecuções vindas de requisição que terminou em erro: "
          f"{_num(m.get('requisicoes_com_erro', 0))} de {_num(m.get('consultas_capturadas', 0))}")


def monitor_origens(ev, a):
    """Quem chamou. Runtime-info quando existe; senao o primeiro frame de negocio."""
    m = ev.get("monitor") or {}
    print(f"{'origem':52}{'consultas':>10}{'exec':>10}{'tempo ms':>12}{'média':>8}")
    for o in (m.get("por_origem") or [])[: a.n]:
        print(f"{_t(o['origem'], 51):52}{o['consultas']:>10}{_num(o['execucoes']):>10}"
              f"{_num(o['tempo_ms']):>12}{o['tempo_medio_ms']:>8.1f}")


def hora(ev, a):
    """Distribuicao por hora do dia, agregada. A serie completa fica em series.json."""
    lg = ev.get("logs") or {}
    agregado = lg.get("por_hora_do_dia")
    if agregado:
        print("hora    entradas      erros")
        for x in agregado:
            print(f"  {x['hora']} {_num(x['entradas']):>11} {_num(x['erros']):>10}")
        return
    # coleta anterior a separacao das series: agrega na hora
    ph = lg.get("por_hora")
    if isinstance(ph, dict):
        print(f"série detalhada em {ph['movido_para']}; recolete para ter o agregado")
        return
    agr = {}
    for x in ph or []:
        d = agr.setdefault(x["hora"][11:13], [0, 0])
        d[0] += x["entradas"]
        d[1] += x["erros"]
    print("hora    entradas      erros")
    for h in sorted(agr):
        print(f"  {h} {_num(agr[h][0]):>11} {_num(agr[h][1]):>10}")


# Conjunto que toda analise le, na ordem em que faz sentido ler. Existe porque
# pedir os recortes um a um custa uma ida e volta por recorte, e a soma dos
# essenciais cabe em ~2,5 mil tokens. Fora daqui ficam os recortes de secao
# especifica (args, drivers, wildfly, monitor-*), que so entram quando aquela
# secao do documento esta sendo escrita.
ESSENCIAIS = ["diagnostico", "ambiente", "banco", "achados", "ciclo", "cpu",
              "sinais", "excecoes", "oracle", "dml", "conexoes", "acessos", "hora"]


def tudo(ev, a):
    """Imprime os recortes essenciais numa chamada, com cabecalho por bloco."""
    for nome in ESSENCIAIS:
        print(f"\n{'=' * 12} {nome}")
        try:
            RECORTES[nome](ev, a)
        except Exception as e:                       # um bloco ausente nao para o resto
            print(f"(falhou: {type(e).__name__}: {e})")


RECORTES = {
    "secoes": secoes, "ambiente": ambiente, "achados": achados, "dml": dml,
    "excecoes": excecoes, "oracle": oracle, "sinais": sinais, "jobs": jobs,
    "conexoes": conexoes, "threads": threads, "acessos": acessos,
    "wildfly": wildfly, "args": args_vm, "drivers": drivers, "hora": hora,
    "banco": banco, "diagnostico": diagnostico, "ciclo": ciclo, "cpu": cpu,
    "tudo": tudo,
    "monitor": monitor, "monitor-atencao": monitor_atencao,
    "monitor-erros": monitor_erros, "monitor-origens": monitor_origens,
}


def main():
    ap = argparse.ArgumentParser(description="Recortes compactos do evidencias.json.")
    ap.add_argument("--evidencias", required=True)
    ap.add_argument("--o", required=True, choices=sorted(RECORTES), help="recorte")
    ap.add_argument("--n", type=int, default=15, help="quantos itens (default 15)")
    ap.add_argument("--sev", choices=["critica", "alta", "media", "baixa"])
    ap.add_argument("--verbose", action="store_true", help="inclui amostras de log")
    a = ap.parse_args()

    with open(a.evidencias, encoding="utf-8") as f:
        ev = json.load(f)
    RECORTES[a.o](ev, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
