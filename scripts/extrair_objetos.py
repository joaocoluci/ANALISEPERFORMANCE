# -*- coding: utf-8 -*-
"""Extrai o OBJETO por tras de uma falha do pacote de log.

O coletor responde "o que" e "quanto". Este script responde "onde": qual entidade,
servico, URI, classe e linha estao por tras de uma assinatura de excecao. E o que
transforma "corrigir a consulta que monta lista grande" em uma recomendacao executavel.

Duas fontes, ambas dentro do proprio server.log:

  Runtime-info  o comentario que o produto embute no SQL antes de manda-lo ao banco.
                Traz `entity`, `service-name` e `uri`. Aparece nas linhas
                `Caused by: Error : NNNN` e nos blocos de PreparedStatement.

  Pilha         os quadros `br.com.sankhya.*` da excecao. O quadro mais alto que nao
                e infraestrutura e o ponto de entrada; o mais baixo antes do
                `Caused by` e onde a falha nasceu.

Le por streaming e NUNCA extrai o zip.

Uso:
    python extrair_objetos.py --pacote server.log_AAAAMMDDHHMMSS.zip \
        --padrao "ORA-01795" [--ocorrencias 3] [--quadros 14] [--saida objetos.json]

`--padrao` e uma expressao regular casada contra a linha do log. Rode uma vez por
assinatura que virou achado, usando o texto que o recorte `--o excecoes` ja devolveu.

CUIDADOS

- **Valor de parametro nunca sai daqui.** `Params:` e `Parametros usados:` sao dado de
  negocio do cliente (documento, valor de titulo, nome de pessoa). O script corta o
  valor e mantem so o rotulo. Nao remover esse corte.
- **O texto do SQL sai truncado de proposito.** O objetivo e nomear a tabela e a
  entidade, nao transcrever a consulta. Consulta inteira e assunto do Monitor de
  Consultas.
- **Numero de linha vale para a versao do modulo daquele pacote.** Ao citar
  `Classe.metodo:1733` no documento, dizer de qual versao do modulo veio.
- Quadro de framework (jdbc, quartz, undertow, tinyejb, cuckoo, reflect) e ruido: o
  script filtra por padrao. `--tudo` mantem todos, para quando a pilha do produto
  estiver vazia.
"""
import argparse
import io
import json
import re
import sys
import zipfile
from collections import Counter

RE_CABECALHO = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ +\w+ +\[[^\]]*\] +\([^)]*\) *"
)
RE_DEPLOY = re.compile(r"at (?:deployment|custom)\.[^/]*//")
RE_ENTITY = re.compile(r"^\s*entity:\s*(\S+)")
RE_SERVICE = re.compile(r"^\s*service-name:\s*(\S+)")
RE_URI = re.compile(r"^\s*uri:\s*(\S+)")
RE_TABELA = re.compile(r"FROM \(SELECT ([A-Z][A-Z0-9_]{2,})\.")
RE_QUADRO = re.compile(r"^\s*at ([\w.$]+\.[\w$<>]+)\(([^)]*)\)")
RE_CAUSA = re.compile(r"^\s*Caused by: (\S+)")
RE_PARAMS = re.compile(r"(?i)^(\s*(?:params|par\S*metros usados)\s*:).*")
# O bloco de parametros nao acaba no rotulo: cada valor vem numa linha propria,
# no formato `param 1 -> class java.lang.String -> 80,90,99`. Sem este segundo
# corte, o rotulo era suprimido e os valores do cliente vazavam logo abaixo.
RE_PARAM_ITEM = re.compile(r"(?i)^(\s*param\s+\d+\s*->\s*(?:class\s+\S+\s*->)?).*")

RUIDO = re.compile(
    r"^(?:java\.|javax\.|jdk\.|sun\.|oracle\.jdbc|org\.jboss|org\.quartz|org\.cuckoo"
    r"|org\.tinyejb|org\.apache|io\.undertow|com\.sun\.proxy)"
)


def limpar(linha, tudo=False):
    """Tira o cabecalho de log, o prefixo de deploy e qualquer valor de parametro."""
    linha = RE_CABECALHO.sub("", linha.rstrip("\n"))
    linha = RE_DEPLOY.sub("at ", linha)
    linha = RE_PARAMS.sub(r"\1 [valor suprimido]", linha)
    return RE_PARAM_ITEM.sub(r"\1 [valor suprimido]", linha)


def arquivos_de_log(zf):
    return [
        n for n in zf.namelist()
        if n.lower().endswith(".log") and "monitor" not in n.lower()
    ]


def coletar(pacote, padrao, ocorrencias, quadros, tudo):
    gatilho = re.compile(padrao)
    entidades, servicos, uris, tabelas = Counter(), Counter(), Counter(), Counter()
    causas, pilha_top = Counter(), Counter()
    amostras = []
    restante = 0
    gravando_amostra = False

    with zipfile.ZipFile(pacote) as zf:
        for nome in arquivos_de_log(zf):
            with zf.open(nome) as fh:
                fluxo = io.TextIOWrapper(fh, encoding="ISO-8859-1", errors="replace")
                for bruta in fluxo:
                    linha = limpar(bruta, tudo)

                    if restante <= 0 and gatilho.search(linha):
                        restante = quadros
                        gravando_amostra = len(amostras) < ocorrencias
                        if gravando_amostra:
                            amostras.append([linha[:180]])
                        continue

                    if restante <= 0:
                        continue
                    restante -= 1

                    achou = RE_ENTITY.match(linha)
                    if achou:
                        entidades[achou.group(1)] += 1
                    achou = RE_SERVICE.match(linha)
                    if achou:
                        servicos[achou.group(1)] += 1
                    achou = RE_URI.match(linha)
                    if achou:
                        uris[achou.group(1)] += 1
                    achou = RE_TABELA.search(linha)
                    if achou:
                        tabelas[achou.group(1)] += 1
                    achou = RE_CAUSA.match(linha)
                    if achou:
                        causas[achou.group(1)] += 1

                    achou = RE_QUADRO.match(linha)
                    if achou:
                        metodo, origem = achou.group(1), achou.group(2)
                        if tudo or not RUIDO.match(metodo):
                            pilha_top["%s(%s)" % (metodo, origem)] += 1

                    if gravando_amostra:
                        amostras[-1].append(linha[:150])

    return {
        "padrao": padrao,
        "entidades": entidades.most_common(15),
        "servicos": servicos.most_common(10),
        "uris": uris.most_common(10),
        "tabelas": tabelas.most_common(15),
        "causas": causas.most_common(10),
        "quadros_do_produto": pilha_top.most_common(25),
        "amostras": amostras[:ocorrencias],
    }


def imprimir(r):
    def bloco(titulo, itens, largura=90):
        if not itens:
            return
        print("== " + titulo)
        for chave, qtd in itens:
            print("   %6d  %s" % (qtd, str(chave)[:largura]))

    print("padrao: %s" % r["padrao"])
    bloco("entidades", r["entidades"])
    bloco("tabelas", r["tabelas"])
    bloco("servicos", r["servicos"])
    bloco("URIs", r["uris"])
    bloco("cadeia de causa", r["causas"])
    bloco("quadros do produto na pilha", r["quadros_do_produto"], 110)
    if r["amostras"]:
        print("== amostra da primeira ocorrencia")
        for linha in r["amostras"][0]:
            print("   " + linha)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pacote", required=True, help="caminho do server.log_*.zip")
    ap.add_argument("--padrao", required=True, help="regex da assinatura a rastrear")
    ap.add_argument("--ocorrencias", type=int, default=2)
    ap.add_argument("--quadros", type=int, default=40,
                    help="linhas lidas apos cada gatilho")
    ap.add_argument("--tudo", action="store_true",
                    help="mantem quadros de framework na pilha")
    ap.add_argument("--saida", help="grava o resultado em JSON")
    args = ap.parse_args()

    try:
        resultado = coletar(args.pacote, args.padrao, args.ocorrencias,
                            args.quadros, args.tudo)
    except re.error as erro:
        sys.exit("padrao invalido: %s" % erro)
    except (OSError, zipfile.BadZipFile) as erro:
        sys.exit("nao foi possivel ler o pacote: %s" % erro)

    imprimir(resultado)
    if args.saida:
        with io.open(args.saida, "w", encoding="utf-8") as fh:
            json.dump(resultado, fh, ensure_ascii=False, indent=1)
        print("\ngravado em %s" % args.saida)


if __name__ == "__main__":
    main()
