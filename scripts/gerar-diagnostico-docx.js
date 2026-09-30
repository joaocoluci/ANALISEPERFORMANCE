/** @author João Coluci **/
/*
 * Gerador do documento "Análise de Performance" em DOCX.
 * Layout: modelo DSTECH v.4 (capa, cabeçalho, rodapé e contracapa) sobre o Modelo de
 * Documento Padrão Sankhya 2026, o mesmo padrão do gerador de orçamento de horas.
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
  WidthType, ShadingType, VerticalAlign, PageNumber, TableLayoutType, TabStopType,
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
// Modelo de Documento Padrão Sankhya 2026 (o mesmo do gerador de orçamento de horas).
// O verde #00D666 só aparece como filete, barra e texto sobre fundo escuro: no branco
// tem contraste 1,9:1 e some na impressão.
const NAVY = "212F41";        // navy 700 — texto, títulos, totais, cabeçalho de tabela
const SLATE = "343C50";       // slate — H3 e texto de caixa de destaque
const GREEN = "00D666";       // verde Sankhya — filetes, barras, destaques na capa
const GREEN_APOIO = "00CD5E"; // verde apoio — rótulos e marcadores sobre fundo claro
const ZEBRA = "F3F3F3";       // cinza claro — linhas alternadas, caixas de destaque
const BORDA = "BFBFBF";       // filete horizontal entre linhas de tabela
const LABEL = "888888";       // cinza — legendas, cabeçalho e rodapé
const TEXT = NAVY;
const FONTE = "Work Sans";
const FONTE_FORTE = "Work Sans SemiBold"; // o padrão 2026 não usa negrito sintético
const FONTE_FINA = "Work Sans Light";

// Página: medidas do modelo DSTECH v.4 (laterais 1304; capa com o texto no terço inferior).
const PAGE = { width: 11906, height: 16838 };
const MARGIN = { top: 2350, bottom: 1300, left: 1304, right: 1304, header: 500, footer: 560 };
const MARGIN_CAPA = { ...MARGIN, top: 6200, header: 600 };
const MARGIN_CONTRACAPA = { ...MARGIN, top: 6600, header: 600 };
const CW = PAGE.width - MARGIN.left - MARGIN.right; // 9298 — largura útil

// Versão e publicação do LAYOUT (modelo DSTECH v.4), não do documento gerado.
const VERSAO_LAYOUT = "4.0";
const DATA_PUBLICACAO_LAYOUT = "30/09/2026";

const filete = { style: BorderStyle.SINGLE, size: 4, color: BORDA };
const semBorda = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const borders = { top: semBorda, bottom: filete, left: semBorda, right: semBorda };
const cellMargins = { top: 100, bottom: 100, left: 140, right: 140 };
const R = AlignmentType.RIGHT;
const C = AlignmentType.CENTER;

// `bold` vira Work Sans SemiBold: a fonte embutida não tem peso negrito.
// `bold` vira Work Sans SemiBold: a fonte embutida não tem peso negrito.
function t(text, opts = {}) {
  const { bold, ...resto } = opts;
  return new TextRun({ text: String(text ?? ""), ...(bold ? { font: FONTE_FORTE } : {}), ...resto });
}
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
  // Texto de tabela do padrão 2026: 9pt; monoespaçado meio ponto menor, porque o
  // Consolas é mais largo que a Work Sans na mesma altura.
  const estilo = {
    bold: bold || header,
    color: header ? "FFFFFF" : undefined,
    font: mono ? "Consolas" : undefined,
    size: mono ? 17 : 18,
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
 * do Consolas e uma media razoavel para Work Sans. E estimativa, entao serve para avisar,
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
    const candidatos = [{ txt: titulo, pt: 9, quebra: false }]
      .concat(corpo.map(c => ({ txt: c, pt: ehMono ? 8.5 : 9, quebra: true })));
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
      border: { left: { style: BorderStyle.SINGLE, size: 36, color: GREEN, space: 12 } },
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
      border: { left: { style: BorderStyle.SINGLE, size: 36, color: GREEN, space: 12 } },
      children: [t("Atenção: ", { bold: true, color: NAVY }), t(b.aviso)],
    }));
  }

  if (grande) {
    saida.push(new Paragraph({
      spacing: { before: 100, after: 60 },
      shading: { fill: ZEBRA, type: ShadingType.CLEAR },
      border: { left: { style: BorderStyle.SINGLE, size: 36, color: GREEN, space: 12 } },
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
    border: { left: { style: BorderStyle.SINGLE, size: 36, color: GREEN, space: 12 } },
    children: [t((titulo || "Observação").toUpperCase() + "  ", { bold: true, color: GREEN_APOIO, characterSpacing: 30 }),
      t(texto, { color: SLATE })],
  });
}

// ---------- capa / cabeçalho / rodapé / contracapa (modelo DSTECH v.4) ----------
// Mesma identidade do Modelo de Documento Padrão Sankhya 2026: capa e contracapa com
// fundo institucional sangrando a página, cabeçalho DSTECH e rodapé com filete verde.
const ASSETS = path.join(__dirname, "..", "assets");
const EMU_PX = 9525;
const PAGINA_EMU = { width: 7562850, height: 10696575 };
const lerAsset = (nome) => fs.readFileSync(path.join(ASSETS, nome));

function fundo(arquivo) {
  return new Paragraph({
    spacing: { before: 0, after: 0 },
    children: [new ImageRun({
      type: "jpg",
      data: lerAsset(arquivo),
      transformation: { width: Math.round(PAGINA_EMU.width / EMU_PX), height: Math.round(PAGINA_EMU.height / EMU_PX) },
      floating: {
        horizontalPosition: { relative: HorizontalPositionRelativeFrom.PAGE, offset: 0 },
        verticalPosition: { relative: VerticalPositionRelativeFrom.PAGE, offset: 0 },
        behindDocument: true,
        wrap: { type: TextWrappingType.NONE },
      },
    })],
  });
}

function linhaCapa(texto, { fina } = {}) {
  return new Paragraph({
    spacing: { before: 0, after: fina ? 0 : 280, line: 240 },
    children: [t(texto.toUpperCase(), {
      font: fina ? FONTE_FINA : FONTE_FORTE, size: 48, characterSpacing: fina ? 30 : 20,
      color: fina ? GREEN : "FFFFFF",
    })],
  });
}

/** Busca na identificação o valor do primeiro rótulo presente (sem diferenciar caixa). */
function valorIdentificacao(rotulos) {
  const alvo = rotulos.map(r => r.toLowerCase());
  const linha = (d.identificacao || []).find(r => alvo.includes(String(r[0]).toLowerCase()));
  return linha ? String(linha[1]) : "";
}

function camposCapa() {
  const cab = d.cabecalho || {};
  const campos = [
    ["Cliente", valorIdentificacao(["Cliente"])],
    ["Versão", cab.versao || "1.0"],
    ["Data", valorIdentificacao(["Data", "Data da análise"])],
    ["Responsável", valorIdentificacao(["Orçamento Realizado por", "Analista"]) || cab.elaborador || "João Coluci"],
  ];
  const w = Math.floor(CW / campos.length);
  const topo = { style: BorderStyle.SINGLE, size: 8, color: GREEN };
  return new Table({
    width: { size: w * campos.length, type: WidthType.DXA }, columnWidths: campos.map(() => w),
    rows: [new TableRow({
      children: campos.map(([rot, val]) => new TableCell({
        width: { size: w, type: WidthType.DXA },
        borders: { top: topo, left: semBorda, bottom: semBorda, right: semBorda },
        margins: { top: 120, bottom: 60, left: 0, right: 200 },
        children: [
          new Paragraph({ spacing: { after: 40 },
            children: [t(rot.toUpperCase(), { font: FONTE_FORTE, color: GREEN, characterSpacing: 40, size: 14 })] }),
          new Paragraph({ spacing: { after: 0 }, children: [t(val, { color: "FFFFFF", size: 18 })] }),
        ],
      })),
    })],
  });
}

/** Título da capa em duas linhas finas (verde) e o nome da demanda em destaque (branco). */
function capa() {
  const titulo = d.titulo || "Análise de Performance";
  const palavras = titulo.split(" ");
  const meio = Math.ceil(palavras.length / 2);
  const out = [fundo("capa-2026.jpg"),
    linhaCapa(palavras.slice(0, meio).join(" "), { fina: true }),
    linhaCapa(palavras.slice(meio).join(" "), { fina: true })];
  if (d.subtitulo) out.push(linhaCapa(d.subtitulo));
  out.push(new Paragraph({ spacing: { before: 3400, after: 0 }, children: [] }));
  out.push(camposCapa());
  return out;
}

function contracapa() {
  const cab = d.cabecalho || {};
  return [
    fundo("contracapa-2026.jpg"),
    linhaCapa("Obrigado.", { fina: true }),
    linhaCapa("Dúvidas? Fale com a gente."),
    new Paragraph({ spacing: { before: 600, after: 20 },
      children: [t((cab.area || "Delivery Service Tech").toUpperCase(), { font: FONTE_FORTE, color: GREEN, characterSpacing: 40, size: 16 })] }),
    new Paragraph({ spacing: { before: 4200 },
      children: [new ImageRun({ type: "png", data: lerAsset("logo-sankhya-branco.png"), transformation: { width: 170, height: 37 } })] }),
  ];
}

function celulaCabecalho(runs, { w, span, align, fill } = {}) {
  return new TableCell({
    borders: { top: semBorda, left: semBorda, right: semBorda, bottom: { style: BorderStyle.SINGLE, size: 4, color: "E4E4E4" } },
    width: { size: w, type: WidthType.DXA }, margins: { top: 50, bottom: 50, left: 110, right: 110 },
    columnSpan: span, verticalAlign: VerticalAlign.CENTER,
    shading: fill ? { fill, type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({ alignment: align, spacing: { before: 0, after: 0, line: 240 }, children: runs })],
  });
}
const rotulo = (txt) => t(txt.toUpperCase(), { font: FONTE_FORTE, size: 13, color: GREEN_APOIO, characterSpacing: 30 });
const valor = (txt) => t(txt, { size: 15, color: NAVY });

/** Tabela DSTECH: elaborador e aprovador do documento; versão e publicação do layout v.4. */
function tabelaCabecalho() {
  const cab = d.cabecalho || {};
  const cols = [1900, 3200, 1700, CW - 6800];
  const logo = new ImageRun({ type: "png", data: lerAsset("logo-sankhya-2026.png"), transformation: { width: 80, height: 17 } });
  const linha = (a, b, c, e) => new TableRow({
    children: [
      celulaCabecalho([rotulo(a)], { w: cols[0], fill: ZEBRA }),
      celulaCabecalho([valor(b)], { w: cols[1] }),
      celulaCabecalho([rotulo(c)], { w: cols[2], fill: ZEBRA }),
      celulaCabecalho([valor(e)], { w: cols[3] }),
    ],
  });
  return new Table({
    width: { size: CW, type: WidthType.DXA }, columnWidths: cols,
    rows: [
      new TableRow({
        children: [
          celulaCabecalho([logo], { w: cols[0] }),
          celulaCabecalho([t((cab.area || "Delivery Service Tech").toUpperCase(),
            { font: FONTE_FORTE, size: 16, color: NAVY, characterSpacing: 30 })],
            { w: cols[1] + cols[2] + cols[3], span: 3, align: R }),
        ],
      }),
      linha("Elaborador", cab.elaborador || "João Coluci", "Versão", VERSAO_LAYOUT),
      linha("Aprovador", cab.aprovador || "Plinio Silva", "Publicação", DATA_PUBLICACAO_LAYOUT),
    ],
  });
}

const cabecalhoPadrao = new Header({
  children: [tabelaCabecalho(), new Paragraph({ spacing: { before: 0, after: 0 }, children: [] })],
});
const vazioCabecalho = () => new Header({ children: [new Paragraph({ children: [] })] });
const vazioRodape = () => new Footer({ children: [new Paragraph({ children: [] })] });
const rodapePadrao = new Footer({
  children: [new Paragraph({
    border: { top: { style: BorderStyle.SINGLE, size: 12, color: GREEN, space: 8 } },
    tabStops: [{ type: TabStopType.RIGHT, position: CW }],
    children: [
      t("SANKHYA  ", { font: FONTE_FORTE, size: 14, color: NAVY, characterSpacing: 30 }),
      t("|  Documento de uso interno e do cliente", { size: 14, color: LABEL }),
      new TextRun({ children: ["\tPÁGINA ", PageNumber.CURRENT, " DE ", PageNumber.TOTAL_PAGES], size: 14, color: LABEL, characterSpacing: 20 }),
    ],
  })],
});

// Fontes embutidas: sem elas o Word troca Work Sans por Calibri em máquina sem a fonte.
const FONTES_EMBUTIDAS = [
  { name: FONTE, data: lerAsset("fontes/WorkSans.ttf") },
  { name: FONTE_FORTE, data: lerAsset("fontes/WorkSansSemiBold.ttf") },
  { name: FONTE_FINA, data: lerAsset("fontes/WorkSansLight.ttf") },
];

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
// Estilos do Modelo de Documento Padrão Sankhya 2026: Work Sans 10,5pt navy; H1 SemiBold em
// caixa alta 17pt; H2 12,5pt; H3 10,5pt slate.
const doc = new Document({
  fonts: FONTES_EMBUTIDAS,
  styles: {
    default: { document: {
      run: { font: FONTE, size: 21, color: TEXT },
      paragraph: { spacing: { after: 140, line: 312 } },
    } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 34, font: FONTE_FORTE, allCaps: true, color: NAVY, characterSpacing: 20 },
        paragraph: { keepNext: true, spacing: { before: 520, after: 220 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 25, font: FONTE_FORTE, color: NAVY },
        paragraph: { keepNext: true, spacing: { before: 320, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 21, font: FONTE_FORTE, color: SLATE },
        paragraph: { keepNext: true, spacing: { before: 240, after: 100 }, outlineLevel: 2 } },
    ],
  },
  numbering: {
    config: [
      { reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "■", alignment: AlignmentType.LEFT,
        style: { run: { color: GREEN_APOIO, size: 14 }, paragraph: { indent: { left: 540, hanging: 300 } } } }] },
      { reference: "n", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { run: { font: FONTE_FORTE, color: GREEN_APOIO }, paragraph: { indent: { left: 540, hanging: 360 } } } }] },
    ],
  },
  sections: [
    { properties: { page: { size: PAGE, margin: MARGIN_CAPA } },
      headers: { default: vazioCabecalho() }, footers: { default: vazioRodape() }, children: capa() },
    { properties: { page: { size: PAGE, margin: MARGIN } },
      headers: { default: cabecalhoPadrao }, footers: { default: rodapePadrao }, children },
    { properties: { page: { size: PAGE, margin: MARGIN_CONTRACAPA } },
      headers: { default: vazioCabecalho() }, footers: { default: vazioRodape() }, children: contracapa() },
  ],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(outputPath, buf);
  console.log("OK " + outputPath);
});
