/** @author João Coluci **/
/*
 * Gerador do documento "Análise de Performance" em DOCX.
 * Layout: modelo DSTECH v.3 (cabeçalho/rodapé) + paleta do Brandbook Sankhya 2023,
 * o mesmo padrão do gerador de orçamento de horas.
 *
 * Uso:
 *   NODE_PATH="$(npm root -g)" node gerar-diagnostico-docx.js --content dados.json --output "Analise.docx"
 *
 * Requer o pacote "docx" instalado globalmente (npm install -g docx).
 * Estrutura do JSON: ver references/schema-diagnostico.md e examples/diagnostico-exemplo.json.
 */
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel, BorderStyle,
  WidthType, ShadingType, VerticalAlign, PageNumber, TableLayoutType,
  HorizontalPositionRelativeFrom, VerticalPositionRelativeFrom, TextWrappingType
} = require("docx");

// ---------- args ----------
function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}
const contentPath = arg("--content");
const outputPath = arg("--output");
if (!contentPath || !outputPath) {
  console.error("Uso: node gerar-diagnostico-docx.js --content dados.json --output saida.docx");
  process.exit(1);
}
const raw = fs.readFileSync(contentPath, "utf8").replace(/^\s*\/\*[\s\S]*?\*\/\s*/, "");
const d = JSON.parse(raw);

// ---------- paleta / medidas ----------
// Brandbook Sankhya 2023. O verde #66CC66 nunca vira texto: 2,2:1 sobre branco
// reprova WCAG AA e some na impressão P&B.
const NAVY = "2E3C50";
const GREEN = "66CC66";
const ZEBRA = "EDEDED";
const GREY = "808285";
const LABEL = "666666";
const TEXT = "000000";

const PAGE = { width: 11906, height: 16838 };
const MARGIN = { top: 1417, bottom: 1417, left: 1700, right: 1700, header: 0, footer: 720 };
const CW = PAGE.width - MARGIN.left - MARGIN.right; // 8506

// Revisão do LAYOUT DSTECH, não do documento gerado.
const DATA_REVISAO_LAYOUT = "03/07/2026";

const border = { style: BorderStyle.SINGLE, size: 2, color: GREY };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 80, bottom: 80, left: 120, right: 120 };
const R = AlignmentType.RIGHT;
const C = AlignmentType.CENTER;

function t(text, opts = {}) { return new TextRun({ text: String(text ?? ""), ...opts }); }
function p(children, opts = {}) {
  return new Paragraph({ children: Array.isArray(children) ? children : [t(children)], ...opts });
}
function h1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [t(text)] }); }
function h1pb(text) { return new Paragraph({ pageBreakBefore: true, heading: HeadingLevel.HEADING_1, children: [t(text)] }); }
function h2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [t(text)] }); }
function h3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [t(text)] }); }
function bullet(txt) { return new Paragraph({ numbering: { reference: "b", level: 0 }, children: [t(txt)] }); }
function numItem(txt) { return new Paragraph({ numbering: { reference: "n", level: 0 }, children: [t(txt)] }); }
function linhaVazia() { return new Paragraph({ spacing: { before: 0, after: 0 }, children: [t("", { size: 22 })] }); }

/*
 * O Word nao quebra palavra no meio. Um nome qualificado como
 * "br.com.sankhya.pes.model.schedules.AtualizacaoCargaHorariaScheduledAction" e um
 * token so, mais largo que qualquer coluna, e estoura a celula mesmo com layout fixo.
 * A saida e oferecer ponto de quebra: um espaco de largura zero (U+200B) depois de cada
 * separador natural do nome. Invisivel na tela e na impressao.
 *
 * So entra em token acima do limite, para nao poluir texto normal. Copiar um nome
 * tratado assim traz o caractere invisivel junto: por isso a regra do documento manda o
 * nome completo para o bloco `evidencia`, que nao reflui e nao passa por aqui.
 */
const LIMITE_TOKEN = 18;
const ZWSP = "​";
const RE_TOKEN_LONGO = new RegExp(`\\S{${LIMITE_TOKEN},}`, "g");
function quebrarTokenLongo(texto) {
  if (typeof texto !== "string") return texto;
  return texto.replace(RE_TOKEN_LONGO, tok => tok
    // separador de pacote, caminho e argumento
    .replace(/([./:_\\-])(?=\S)/g, `$1${ZWSP}`)
    // nome em camelCase nao tem separador nenhum: "AtualizacaoCargaHorariaScheduledAction"
    // e uma palavra so. A troca de minuscula para maiuscula e o ponto de quebra natural.
    .replace(/([a-z0-9])(?=[A-Z])/g, `$1${ZWSP}`));
}

function cell(content, { w, fill, bold, align, header, span, mono } = {}) {
  // Conteudo com "\n" vira uma linha por item: lista de objetos empilha em vez de
  // alargar a coluna. Cada linha e um paragrafo proprio, sem espaco entre eles.
  const linhas = Array.isArray(content) ? null : String(content).split("\n");
  // Cabecalho um ponto menor que o corpo: com 11pt, rotulo comum como "Responsavel" ou
  // "Prioridade" nao cabia na coluna e o Word partia a palavra no meio ("Responsav/el").
  const estilo = {
    bold: bold || header,
    color: header ? "FFFFFF" : undefined,
    font: mono ? "Consolas" : undefined,
    size: mono ? 18 : (header ? 20 : undefined),
  };
  const paragrafos = Array.isArray(content)
    ? [new Paragraph({ alignment: align, children: content })]
    // A quebra suave vale para qualquer celula, nao so para a monoespacada: caminho de
    // diretorio e nome de classe aparecem em coluna de texto normal tambem. Palavra
    // comum do portugues nao chega ao limite de 18 caracteres, entao a prosa passa ilesa.
    // O cabecalho fica de fora: rotulo que nao cabe e erro de largura, e o aviso da
    // geracao existe para expo-lo, nao para escondê-lo com quebra invisivel.
    : linhas.map((linha, i) => new Paragraph({
        alignment: align,
        spacing: { before: i === 0 ? 0 : 20, after: 0 },
        children: [t(header ? linha : quebrarTokenLongo(linha), estilo)],
      }));
  return new TableCell({
    borders, width: { size: w, type: WidthType.DXA }, margins: cellMargins,
    verticalAlign: VerticalAlign.CENTER, columnSpan: span,
    shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
    children: paragrafos,
  });
}

/** Distribui a largura útil entre as colunas conforme os pesos informados. */
function larguras(n, pesos) {
  const w = pesos && pesos.length === n ? pesos : Array(n).fill(1);
  const soma = w.reduce((a, b) => a + b, 0);
  const cols = w.map(x => Math.floor(CW * x / soma));
  cols[n - 1] += CW - cols.reduce((a, b) => a + b, 0);
  return cols;
}

/*
 * Aviso de coluna estreita.
 *
 * O Word so parte palavra no meio quando ela nao cabe de jeito nenhum, e o resultado
 * ("Responsav/el", "Med/ia", um "10" empilhado como "1" e "0") passa despercebido no
 * JSON: so aparece no PDF. Aqui a conta e feita na geracao.
 *
 * Largura util da celula = largura da coluna menos as duas margens (240 DXA). 20 DXA
 * valem 1 pt. A largura media do caractere e estimada em 0,55 em, que e a largura exata
 * do Consolas e uma media razoavel para Arial. E estimativa, entao serve para avisar,
 * nunca para abortar.
 */
const MARGEM_CELULA = 240;
const EM_MEDIO = 0.55;
function avisarColunaEstreita(colunas, linhas, cols, opts) {
  const mono = opts.monoCols || [];
  colunas.forEach((titulo, i) => {
    const ptUtil = (cols[i] - MARGEM_CELULA) / 20;
    const ehMono = mono.includes(i);
    const corpo = linhas.map(r => String(r[i] ?? ""));
    // O cabecalho nunca passa pela quebra suave, entao entra inteiro.
    const candidatos = [{ txt: titulo, pt: 10, quebra: false }]
      .concat(corpo.map(c => ({ txt: c, pt: ehMono ? 9 : 11, quebra: true })));
    for (const { txt, pt, quebra } of candidatos) {
      const preparado = quebra ? quebrarTokenLongo(txt) : txt;
      const tokens = preparado.split(/[\s​\n]+/).filter(Boolean);
      for (const tok of tokens) {
        const larguraPt = tok.length * pt * EM_MEDIO;
        if (larguraPt > ptUtil) {
          console.warn(
            `aviso: coluna "${titulo}" tem ${ptUtil.toFixed(0)}pt uteis e "${tok}" ` +
            `precisa de ~${larguraPt.toFixed(0)}pt. O Word vai partir a palavra no meio.`);
          return;
        }
      }
    }
  });
}

function tabela(colunas, linhas, opts = {}) {
  const cols = larguras(colunas.length, opts.pesos);
  avisarColunaEstreita(colunas, linhas, cols, opts);
  const aligns = opts.aligns || [];
  const trHeader = new TableRow({
    tableHeader: true,
    children: colunas.map((c, i) => cell(c, { w: cols[i], fill: NAVY, header: true, align: aligns[i] })),
  });
  // Linha de tabela nao se parte entre paginas: o leitor perdia metade da acao no rodape
  // e a outra metade no topo da pagina seguinte, sem o cabecalho por perto.
  const trRows = linhas.map((r, ri) => new TableRow({
    cantSplit: true,
    children: r.map((c, i) => cell(c, {
      w: cols[i],
      fill: ri % 2 === 1 ? ZEBRA : undefined,
      bold: (opts.boldCols || []).includes(i),
      align: aligns[i],
      mono: (opts.monoCols || []).includes(i),
    })),
  }));
  // Sem layout fixo o Word trata columnWidths como sugestao e refaz as colunas pelo
  // conteudo. Os pesos declarados no JSON viravam enfeite e a tabela saia torta.
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: cols,
    layout: TableLayoutType.FIXED, rows: [trHeader, ...trRows],
  });
}

/** Trecho de log. Monoespaçado, fundo cinza, barra verde. Nunca reflui. */
function evidencia(linhas, legenda) {
  const out = [];
  const lista = Array.isArray(linhas) ? linhas : [linhas];
  lista.forEach((l, i) => {
    out.push(new Paragraph({
      spacing: { before: i === 0 ? 120 : 0, after: i === lista.length - 1 ? 60 : 0 },
      shading: { fill: ZEBRA, type: ShadingType.CLEAR },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 8 } },
      children: [t(l, { font: "Consolas", size: 16 })],
    }));
  });
  if (legenda) {
    out.push(new Paragraph({
      spacing: { after: 140 },
      children: [t(legenda, { size: 16, color: LABEL, italics: true })],
    }));
  }
  return out;
}

/**
 * Bloco de script SQL, para o cliente copiar e executar.
 *
 * Diferente de `evidencia`, que é trecho de log e vai truncado em ~110
 * caracteres: aqui o texto precisa sobreviver à cópia. Por isso a fonte cai a
 * 8pt (16 half-points) e não há barra verde à esquerda — a barra é borda de
 * parágrafo, e o Word a copia junto com o texto em algumas versões.
 *
 * O SQL é lido do arquivo e escrito linha a linha, sem reflow. Linha mais
 * longa que a margem é aparada na impressão, mas a cópia sai íntegra.
 */
function blocoSql(b, saida) {
  const caminho = path.isAbsolute(b.arquivo)
    ? b.arquivo
    : path.join(path.dirname(contentPath), b.arquivo);
  if (!fs.existsSync(caminho)) {
    console.error(`Script SQL não encontrado: ${caminho}`);
    process.exit(1);
  }
  // Comentário de autoria injetado por hook não é conteúdo do script.
  const sql = fs.readFileSync(caminho, "utf8")
    .replace(/^\s*\/\*\*?\s*@author[\s\S]*?\*\*?\/\s*\r?\n/, "")
    .replace(/\s+$/, "");

  // Script de terceiro pode ser enorme: `sp_WhoIsActive` tem 134 KB, que são
  // ~37 mil tokens e dezenas de páginas de DOCX. Transcrever isso não ajuda
  // ninguém a copiar, e um dia alguém vai ler o arquivo inteiro em contexto.
  // Acima do limite, o documento aponta o arquivo em vez de despejá-lo.
  const LIMITE_LINHAS = 120;
  const LIMITE_BYTES = 12000;
  const linhasSql = sql.split(/\r?\n/);
  const grande = linhasSql.length > LIMITE_LINHAS || sql.length > LIMITE_BYTES;

  if (b.titulo) saida.push(h3(b.titulo));
  if (b.responde) {
    saida.push(new Paragraph({
      spacing: { before: 40, after: 60 },
      children: [t("O que responde: ", { bold: true, color: NAVY }), t(b.responde)],
    }));
  }
  if (b.aviso) {
    saida.push(new Paragraph({
      spacing: { before: 60, after: 100 },
      shading: { fill: ZEBRA, type: ShadingType.CLEAR },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 8 } },
      children: [t("Atenção: ", { bold: true, color: NAVY }), t(b.aviso)],
    }));
  }

  if (grande) {
    saida.push(new Paragraph({
      spacing: { before: 100, after: 60 },
      shading: { fill: ZEBRA, type: ShadingType.CLEAR },
      border: { left: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 8 } },
      children: [
        t("Script entregue em arquivo: ", { bold: true, color: NAVY }),
        t(`${path.basename(caminho)}, ${linhasSql.length} linhas e ` +
          `${Math.round(sql.length / 1024)} KB. Transcrever um script deste tamanho ` +
          `não ajuda a copiar, e por isso ele segue anexo a este documento.`),
      ],
    }));
    // As primeiras linhas de comentário dizem o que o script faz e como usá-lo.
    linhasSql.filter(l => l.trim().startsWith("--")).slice(0, 8).forEach(l => {
      saida.push(new Paragraph({
        spacing: { before: 0, after: 0, line: 200 },
        shading: { fill: ZEBRA, type: ShadingType.CLEAR },
        children: [t(l, { font: "Consolas", size: 16 })],
      }));
    });
  } else {
    linhasSql.forEach((l, i) => {
      saida.push(new Paragraph({
        spacing: { before: i === 0 ? 100 : 0, after: i === linhasSql.length - 1 ? 60 : 0, line: 200 },
        shading: { fill: ZEBRA, type: ShadingType.CLEAR },
        children: [t(l || " ", { font: "Consolas", size: 16 })],
      }));
    });
  }

  saida.push(new Paragraph({
    spacing: { after: 200 },
    children: [t(`Arquivo: ${path.basename(caminho)}` +
                 (b.origem ? ` · ${b.origem}` : ""),
                 { size: 16, color: LABEL, italics: true })],
  }));
}

/** Caixa de destaque: observação, conclusão, alerta de limitação. */
function destaque(titulo, texto) {
  return new Paragraph({
    spacing: { before: 160, after: 160 },
    shading: { fill: ZEBRA, type: ShadingType.CLEAR },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 8 } },
    children: [t((titulo || "Observação") + ": ", { bold: true, color: NAVY }), t(texto)],
  });
}

// ---------- cabeçalho / rodapé (modelo DSTECH v.3) ----------
const ASSETS = path.join(__dirname, "..", "assets");
const EMU_PX = 9525;
function faixa(file, wEmu, hEmu, xEmu, yEmu) {
  return new ImageRun({
    type: "png",
    data: fs.readFileSync(path.join(ASSETS, file)),
    transformation: { width: Math.round(wEmu / EMU_PX), height: Math.round(hEmu / EMU_PX) },
    floating: {
      horizontalPosition: { relative: HorizontalPositionRelativeFrom.COLUMN, offset: xEmu },
      verticalPosition: { relative: VerticalPositionRelativeFrom.PARAGRAPH, offset: yEmu },
      behindDocument: true,
      wrap: { type: TextWrappingType.NONE },
    },
  });
}

function celulaCabecalho(runs, { w, span, align } = {}) {
  const dotted = { style: BorderStyle.DOTTED, size: 4, color: "000000" };
  return new TableCell({
    borders: { top: dotted, bottom: dotted, left: dotted, right: dotted },
    width: { size: w, type: WidthType.DXA }, margins: { top: 100, bottom: 100, left: 100, right: 100 },
    columnSpan: span, verticalAlign: VerticalAlign.CENTER,
    children: [new Paragraph({ alignment: align, spacing: { before: 0, after: 0 }, children: runs })],
  });
}
function rotulo(txt) { return t(txt, { size: 16, color: LABEL }); }

function tabelaCabecalho() {
  const cab = d.cabecalho || {};
  const cols = [1530, 3810, 1335, 1815];
  const logo = new ImageRun({
    type: "png",
    data: fs.readFileSync(path.join(ASSETS, "logo-sankhya.png")),
    transformation: { width: 59, height: 34 },
  });
  const linha = (a, b, c, e) => new TableRow({
    children: [
      celulaCabecalho([rotulo(a)], { w: cols[0] }),
      celulaCabecalho([rotulo(b)], { w: cols[1] }),
      celulaCabecalho([rotulo(c)], { w: cols[2] }),
      celulaCabecalho([rotulo(e)], { w: cols[3] }),
    ],
  });
  return new Table({
    width: { size: 8490, type: WidthType.DXA }, columnWidths: cols,
    layout: TableLayoutType.FIXED,
    rows: [
      new TableRow({
        children: [
          celulaCabecalho([logo], { w: cols[0], align: C }),
          celulaCabecalho([t(cab.area || "Delivery Service Tech", { bold: true, size: 20, color: NAVY })],
            { w: cols[1] + cols[2] + cols[3], span: 3, align: C }),
        ],
      }),
      linha("Elaborador", cab.elaborador || "João Coluci", "Versão", cab.versao || "1.0"),
      linha("Aprovador", cab.aprovador || "Plinio Silva", "Data Revisão", DATA_REVISAO_LAYOUT),
    ],
  });
}

const vazio = (n) => Array.from({ length: n }, () => new Paragraph({ spacing: { before: 0, after: 0 }, children: [t("", { size: 20 })] }));

const cabecalhoPadrao = new Header({
  children: [
    new Paragraph({ spacing: { before: 0, after: 0 }, children: [faixa("cabecalho-padrao.png", 7479882, 414338, -1076322, 1)] }),
    ...vazio(3),
    tabelaCabecalho(),
    new Paragraph({ spacing: { before: 0, after: 0 }, children: [] }),
  ],
});
const cabecalhoCapa = new Header({
  children: [new Paragraph({ spacing: { before: 0, after: 0 }, children: [faixa("cabecalho-capa.png", 7581900, 1185863, -1079998, 1)] })],
});
const rodapePadrao = new Footer({
  children: [new Paragraph({
    alignment: R,
    children: [
      new TextRun({ children: [PageNumber.CURRENT], size: 16, color: LABEL }),
      faixa("rodape-padrao.png", 7572375, 658544, -1076322, 1),
    ],
  })],
});
const rodapeCapa = new Footer({
  children: [new Paragraph({ children: [faixa("rodape-capa.png", 7581900, 855931, -1076322, -126760)] })],
});

// ---------- blocos ----------
// Cada bloco do JSON vira um ou mais parágrafos. Tipo desconhecido aborta a
// geração: silenciar bloco não reconhecido produz documento com seção faltando
// sem ninguém perceber.
function renderBloco(b, saida) {
  switch (b.tipo) {
    case "paragrafo":
      saida.push(p(b.texto));
      break;

    case "lista":
      (b.itens || []).forEach(x => saida.push(bullet(x)));
      break;

    case "numerada":
      (b.itens || []).forEach(x => saida.push(numItem(x)));
      break;

    case "tabela":
      saida.push(linhaVazia());
      saida.push(tabela(b.colunas, b.linhas, {
        pesos: b.pesos, aligns: b.aligns, boldCols: b.boldCols, monoCols: b.monoCols,
      }));
      if (b.legenda) {
        saida.push(new Paragraph({ spacing: { before: 60, after: 120 },
          children: [t(b.legenda, { size: 16, color: LABEL, italics: true })] }));
      } else {
        saida.push(linhaVazia());
      }
      break;

    case "evidencia":
      evidencia(b.linhas || b.texto, b.legenda).forEach(x => saida.push(x));
      break;

    case "destaque":
      saida.push(destaque(b.titulo, b.texto));
      break;

    case "imagem":
      renderImagem(b, saida);
      break;

    case "achado":
      renderAchado(b, saida);
      break;

    case "subtitulo":
      saida.push(h3(b.texto));
      break;

    case "sql":
      blocoSql(b, saida);
      break;

    default:
      console.error(`Bloco de tipo desconhecido: "${b.tipo}". Ver references/schema-diagnostico.md.`);
      process.exit(1);
  }
}

/**
 * Gráfico. A largura útil da página é 8506 twips = 15,0 cm; os PNGs saem do
 * gerador de gráficos já nessa largura, a 200 dpi. Aqui a imagem é inserida em
 * pontos (1 pt = 20 twips), mantendo a proporção lida do próprio arquivo, para
 * que ela não seja esticada nem estourada para fora da margem.
 *
 * A legenda é obrigatória: ela diz a fonte e o período, e é o que sobra quando
 * o documento é impresso em preto e branco.
 */
function renderImagem(b, saida) {
  const caminho = path.isAbsolute(b.arquivo)
    ? b.arquivo
    : path.resolve(path.dirname(contentPath), b.arquivo);
  if (!fs.existsSync(caminho)) {
    console.error(`Imagem não encontrada: ${caminho}`);
    process.exit(1);
  }
  const dados = fs.readFileSync(caminho);
  const { width, height } = tamanhoPng(dados);
  const larguraPt = (b.larguraTwips || CW) / 20;
  const alturaPt = Math.round(larguraPt * (height / width));

  saida.push(new Paragraph({
    alignment: C,
    spacing: { before: 160, after: b.legenda ? 40 : 160 },
    children: [new ImageRun({
      type: "png",
      data: dados,
      transformation: { width: Math.round(larguraPt), height: alturaPt },
    })],
  }));
  if (b.legenda) {
    saida.push(new Paragraph({
      alignment: C,
      spacing: { after: 180 },
      children: [t(b.legenda, { size: 16, color: LABEL, italics: true })],
    }));
  }
}

/** Lê largura e altura do cabeçalho IHDR de um PNG, sem dependência externa. */
function tamanhoPng(buf) {
  const assinatura = buf.readUInt32BE(0) === 0x89504e47;
  if (!assinatura) {
    console.error("Arquivo de gráfico não é um PNG válido.");
    process.exit(1);
  }
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

/**
 * Achado: a unidade do diagnóstico. Sempre nesta ordem — o que foi observado,
 * o que isso custa, o que provavelmente causa, o que fazer. Evidência sem
 * impacto vira curiosidade; impacto sem evidência vira opinião.
 */
function renderAchado(a, saida) {
  const sev = (a.severidade || "").toUpperCase();
  saida.push(new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [t(a.titulo), ...(sev ? [t("   ·   " + sev, { size: 20 })] : [])],
  }));
  const campos = [
    ["Evidência", a.evidencia],
    ["Impacto", a.impacto],
    ["Causa provável", a.causa],
    ["Ação recomendada", a.acao],
  ];
  for (const [rot, val] of campos) {
    if (!val) continue;
    saida.push(new Paragraph({
      spacing: { before: 100, after: 40 },
      children: [t(rot + ": ", { bold: true, color: NAVY }), t(val)],
    }));
  }
  if (a.trecho) {
    evidencia(a.trecho, a.legendaTrecho).forEach(x => saida.push(x));
  }
  if (a.grafico) {
    renderImagem(a.grafico, saida);
  }
  if (a.tabela) {
    saida.push(linhaVazia());
    saida.push(tabela(a.tabela.colunas, a.tabela.linhas, {
      pesos: a.tabela.pesos, aligns: a.tabela.aligns, monoCols: a.tabela.monoCols,
    }));
    saida.push(linhaVazia());
  }
}

// ---------- montagem ----------
const children = [];

children.push(new Paragraph({
  alignment: C, spacing: { after: 60 },
  children: [t(d.titulo || "Análise de Performance", { bold: true, size: 40, color: NAVY })],
}));
if (d.subtitulo) {
  children.push(new Paragraph({
    alignment: C, spacing: { after: 240 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 4 } },
    children: [t(d.subtitulo, { bold: true, size: 26, color: NAVY })],
  }));
}

if (d.identificacao?.length) {
  children.push(tabela(["Campo", "Valor"], d.identificacao.map(r => [r[0], r[1]]),
    { pesos: [1, 2.2], boldCols: [0] }));
  children.push(p("", { spacing: { after: 120 } }));
}

for (const s of (d.secoes || [])) {
  const titulo = s.titulo || "";
  if (s.nivel === 2) children.push(h2(titulo));
  else if (s.quebraPagina) children.push(h1pb(titulo));
  else children.push(h1(titulo));
  for (const b of (s.blocos || [])) renderBloco(b, children);
}

// ---------- documento ----------
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: TEXT } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 22, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 200, after: 40 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 620, hanging: 320 } } } }] },
      { reference: "n", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 620, hanging: 320 } } } }] },
    ],
  },
  sections: [{
    properties: { titlePage: true, page: { size: PAGE, margin: MARGIN } },
    headers: { default: cabecalhoPadrao, first: cabecalhoCapa },
    footers: { default: rodapePadrao, first: rodapeCapa },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outputPath, buf);
  console.log("OK " + outputPath);
});
