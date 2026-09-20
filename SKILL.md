---
name: analise-performance
description: >
  Analisa o pacote de log do Sankhya (server.log_AAAAMMDDHHMMSS.zip) e, quando vier junto,
  o pacote do Monitor de Consultas (Monitoramento*.zip com Monitor_Consulta.log e
  Monitor_Processos.log), e gera o documento "Análise de Performance" em DOCX no padrão
  DSTECH v.3 — ambiente, perfil de carga, gargalos com evidência, consultas ofensivas
  pontuadas, consultas com erro, gráficos e recomendações priorizadas. Acionar para
  "análise de performance", "diagnóstico de performance", "analisar o log do cliente",
  "o cliente está com lentidão", "abrir o pacote de log", "por que o Sankhya está lento",
  "consultas mais lentas", "monitor de consultas", "diagnóstico do ambiente", ou quando o
  usuário apontar uma pasta com os pacotes de coleta.
  Não usar para estimar horas (orcamento-horas-docx) nem para escrever escopo.
---

# Análise de Performance do ambiente Sankhya

Recebe o pacote de coleta de logs, mede, cruza as fontes e entrega um diagnóstico onde
**cada afirmação carrega o número que a sustenta**.

## A regra que organiza tudo

Um achado precisa de **número medido, fonte e janela de tempo**. Faltando qualquer uma,
não é achado: é hipótese, e vai para as verificações complementares com o comando que a
confirmaria.

E precisa do **objeto**, sempre que o pacote permitir nomeá-lo: a classe, o serviço, a
entidade, a tabela, a procedure, o módulo, a URI, o argumento ou o script que a ação vai
tocar. "Corrigir a consulta que monta lista grande" não é executável; "quebrar o filtro em
`CRUDServiceProviderBean.loadRecords` para as entidades Cargo e Departamento, tabelas
`TFPCAR` e `TFPDEP`" é. Sem objeto, a recomendação volta como pergunta no e-mail seguinte,
e o cliente não sabe a quem encaminhar. Onde procurar o objeto: seção **2.1**.

O erro típico aqui não é deixar de encontrar problema. É afirmar causa a partir de
correlação: ver `OutOfMemoryError` e escrever "vazamento de memória"; ver DELETE lento e
escrever "falta índice". O pacote prova **efeito**, e aponta onde olhar.

"Média de 1.607 ms contra 350 ms de referência" é o que o pacote prova. "A tabela está sem
índice" é o que ele não prova. Mesma distância entre "o erro ocorreu 47 vezes entre 10h e
11h" e "o servidor está sobrecarregado".

## Fluxo

### 0. Recorte

Alinhar antes de rodar: **caminho do pacote** (e do pacote do monitor, se houver);
**sintoma relatado** (generalizada,
localizada, ou em horário específico — muda a lista de hipóteses, ver
`catalogo-gargalos.md`); **cliente e período**. Sem o sintoma, seguir com os três abertos
e dizer isso no documento. Perguntas em `questionario-lentidao.md`.

Vindo o pacote do monitor, perguntar também **quando o monitor ficou ligado**: ele não
grava horário, e sem essa resposta não se afirma que a janela dele cobre o sintoma.

### 1. Coletar

```bash
python "$HOME/.claude/skills/analise-performance/scripts/coletar_metricas.py" \
  --pacote "/caminho/server.log_AAAAMMDDHHMMSS.zip" --saida "/caminho/analise"
```

Lê por streaming; **nunca extrair o zip**. 2,5 GB levam ~10 min: rodar em background.
`--rapido` limita a 200 MB por arquivo, só para inspeção prévia, e o documento tem de
dizer que o resultado é parcial.

Saída: `resumo.md` (digest), `evidencias.json` (agregados) e `series.json` (séries
densas, só para os gráficos).

**Pacote do Monitor de Consultas.** O coletor procura sozinho, na pasta do pacote de log,
um zip que contenha `Monitor_Consulta.log` — reconhece pelo conteúdo, porque o nome vem do
navegador (`Monitoramento (15).zip`). Achando, vira o bloco `monitor` do mesmo
`evidencias.json`. `--monitor CAMINHO` aponta outro; `--sem-monitor` ignora o que estiver
ao lado. Vindo só o pacote do monitor, `coletar_monitor.py --monitor ... --saida ...` roda
sozinho e escreve `monitor.json` e `monitor.md`. Formato das duas fontes e o que elas
**não** respondem: `fontes-pacote-log.md`.

Ao mexer em qualquer padrão de detecção, rodar `testar_sinais.py` antes. Padrão que casa a
coisa errada não falha: entrega um achado convincente e falso. Cinco já passaram por aqui;
o teste os pega em dois segundos.

### 2. Ler

Ler o `resumo.md`, depois **uma chamada** para o conjunto essencial:

```bash
python "$HOME/.claude/skills/analise-performance/scripts/consultar.py" \
  --evidencias /caminho/analise/evidencias.json --o tudo
```

`--o tudo` custa ~3 mil tokens e cobre treze recortes: `diagnostico ambiente banco achados
ciclo cpu sinais excecoes oracle dml conexoes acessos hora`. Pedir um a um custa uma ida e
volta por recorte e dá o mesmo resultado.

Recortes de seção específica, sob demanda: `args` (seção 8), `wildfly` e `drivers` (seção
9), `secoes`, `threads`, `jobs`, `monitor*`. Aceita `--sev`, `--n`, `--verbose`.

Três valem nota:

- **`--o diagnostico`** é o de maior poder por token. Traz o bloco que o próprio Sankhya
  monta no pacote, com **valor medido e limite recomendado lado a lado**, mais o
  estereótipo da base. É o que desmente achado automático: heap "a 100%" com GC em 0,09%
  não é pressão de memória, e lentidão de produção não se analisa em base TESTE;
- **`--o banco`** antes de qualquer recomendação com script, ver 3.1;
- **`--o cpu`** dá CPU por família de thread com os **dois denominadores**. Confundi-los
  muda a conclusão: `%vivas` é sobre as threads do dump, `%proc` é sobre a CPU que o
  processo consumiu desde que subiu.

Um `Read` no `evidencias.json` custa ~39 mil tokens. **Nunca abrir `series.json`** — são
milhares de pontos que só os gráficos consomem.

**Antes de escavar o zip com script próprio, procurar o dado nos recortes.** Subida do
servidor, componentes que não subiram, republicações de módulo, falhas de migração e CPU
por família já estão em `--o ciclo` e `--o cpu`; linha de amostra de exceção sai em
`--o excecoes --verbose`. Escavação a mão foi medida em ~24 mil tokens numa análise, contra
~5 mil do caminho acima.

### 2.1 Onde está o objeto

O coletor responde "o que" e "quanto". Ele não responde "onde", e é o "onde" que torna a
recomendação executável. Para cada assinatura que virar achado:

```bash
python "$HOME/.claude/skills/analise-performance/scripts/extrair_objetos.py" \
  --pacote "/caminho/server.log_AAAAMMDDHHMMSS.zip" --padrao "ORA-01795" --quadros 30
```

Devolve, agregado por contagem: entidade, tabela, serviço, URI, cadeia de causa e os
quadros `br.com.sankhya` da pilha. Custa uma varredura e ~1 mil tokens de saída, contra as
~24 mil da escavação a mão que este arquivo já adverte em 2.

Três coisas que decidem o resultado:

- **o padrão certo muda o que sai.** `Runtime-info` fica colado na linha
  `Caused by: Error : NNNN`, não na mensagem de negócio: rastreando `ORA-01795` saem os
  quadros, rastreando `Error : 1795, Position` sai `entity: Cargo`. Na dúvida, rodar os
  dois;
- **o quadro que interessa não é o primeiro.** `MGEModelException.parse` aparece em toda
  falha. Quem nomeia o objeto é o quadro de negócio: `CRUDServiceProviderBean.loadRecords`,
  `FuncionariosRepository.atualizarCargaHoraria`, `MatrizRiscoService`;
- **a pilha às vezes fecha a causa**, e aí ela deixa de ser hipótese. Uma rotina agendada
  sob `DefaultSchedulerEnvironment.runWithoutTransaction` chamando um método que termina em
  `EntityContainer.assertOpenTransaction` **é** gravação fora de transação, não uma leitura
  possível. Quando a pilha fecha, o achado diz que fecha.

Antes disso, olhar `excecoes[].assinatura` e `.amostra` no `evidencias.json`: o nome
completo da classe ausente e o nome da entidade costumam estar ali, sem custo de varredura.

Objeto citado carrega o que ele é. `TFPCAR` é tabela, `Cargo` é entidade,
`CRUDServiceProvider.loadRecords` é serviço, `turnkey.ear` é módulo,
`jape.global.query.timeout` é argumento. Trocar um pelo outro faz o cliente procurar no
lugar errado.

**Número de linha envelhece.** `FuncionariosRepository.atualizarCargaHoraria:1733` vale
para a versão do módulo daquele pacote: citar a versão junto, ou o desenvolvedor abre outra
linha e conclui que o documento está errado.

### 3. Interpretar

Os `achados` do JSON são **saída de limiar, não diagnóstico**:

- **descartar** o que não tem efeito prático, registrando o motivo quando não for óbvio;
- **cruzar** fontes — um erro às 10h07 que coincide com o pico de conexões e com o objeto
  mais lento é um achado; cada um isolado é ruído;
- **agrupar** sintomas de mesma causa em um achado;
- **ordenar** por efeito no usuário, não por facilidade de correção.

`catalogo-gargalos.md` traz limiar, causa provável e, sobretudo, o que cada evidência
**não** prova. O bloco do monitor é o 2.6: pontuação, erros e pontos de atenção.

Duas armadilhas próprias do monitor:

- **pontuação não é causa.** Falta de índice, estatística velha e volume legítimo dão a
  mesma pontuação. Quem separa é o plano de execução, que não está no pacote;
- **janela diferente é assunto diferente.** Monitor benigno com `dml_stats` pesado não é
  contradição: são janelas distintas, e o monitor não registra horário. Quando as fontes
  discordam, o documento diz que discordam.

### 3.1 Dialeto do banco

Toda recomendação que termina em script depende de saber **qual banco**. O coletor resolve
isso no bloco `banco`, por precedência: URL do datasource, banner do log, classe do driver
do datasource, driver único carregado. A lista de drivers carregados nunca decide (ver
*Cuidados*).

Discordando URL e banner, o campo `conflito` guarda as duas leituras. A URL prevalece, e o
documento **diz que discordam** em vez de escolher em silêncio. Sem nenhuma das quatro
fontes não há dialeto: a seção 12 sai e a impossibilidade entra nas limitações, com o
pedido do `mge-ds.xml`.

Os scripts vivem em `references/scripts-sql/`, e `catalogo.json` mapeia pergunta → arquivo
por dialeto. Os de Oracle vêm do checklist do Service Desk; os de SQL Server, exceto os
dois `sp_WhoIsActive`, são autorais da skill e marcados como não homologados — a marca vai
para o documento, não fica só no arquivo.

### 4. Redigir

Estrutura, regras de conteúdo, dados pessoais e detalhe das seções:
`estrutura-documento.md`.

**Seção 12, scripts para execução.** Um bloco `sql` por script aplicável, com o caminho
saindo de `banco.scripts.aplicaveis[].arquivo` — nunca de memória. Script de `tipo` `ddl`
ou `objeto` exige o campo `aviso`. Regras completas em `estrutura-documento.md`.

**Todo texto passa pela skill `humanizer` antes de virar JSON.** Antes, não depois:
humanizar o JSON montado arrisca reescrever número e rótulo. Campos que passam e que não
passam: `schema-diagnostico.md`.

### 5. Gráficos

```bash
python "$HOME/.claude/skills/analise-performance/scripts/gerar_graficos.py" \
  --evidencias /caminho/analise/evidencias.json --saida /caminho/analise/graficos
```

Requer `matplotlib`. Regras no cabeçalho do script e em `estrutura-documento.md`. Duas
que não podem ser esquecidas: **nunca dois eixos y no mesmo plano**, e **abrir os PNG e
olhar** antes de embutir.

Do monitor saem `07-monitor-pontuacao`, `08-monitor-faixas`, `09-monitor-origens` e
`10-monitor-erros`. O de erros só sai com volume que justifique (três consultas distintas
ou dez ocorrências): uma barra com uma ocorrência diz menos que a tabela e sugere volume
que não existe.

### 6. Gerar e validar

```bash
npm ls -g docx || npm install -g docx
export NODE_PATH="$(npm root -g)"
node "$HOME/.claude/skills/analise-performance/scripts/gerar-diagnostico-docx.js" \
  --content /caminho/dados.json --output "/caminho/Analise de Performance - Cliente.docx"

export PYTHONUTF8=1
python "$HOME/.claude/skills/docx/scripts/office/validate.py" "/caminho/Analise.docx"
```

Esperado: `All validations PASSED!` **e nenhum `aviso:` na saída do gerador.** O aviso de
coluna estreita diz que o Word vai partir uma palavra no meio; ele não aborta a geração,
e ignorá-lo entrega tabela torta ao cliente. Ou a coluna cresce, ou o texto encurta. A
aritmética de largura está em `schema-diagnostico.md`.

### 7. Conferir o PDF

As duas checagens acima não olham a página. Um documento pode passar nas duas e sair com
coluna desalinhada, palavra partida ou linha cortada na virada de página. Exportar e olhar:

```powershell
$w = New-Object -ComObject Word.Application; $w.Visible = $false
$d = $w.Documents.Open("C:\caminho\Analise.docx", $false, $true)
$d.ExportAsFixedFormat("C:\caminho\conferencia.pdf", 17)
$d.Close($false); $w.Quit()
```

Depois renderizar as páginas das tabelas grandes com `pypdfium2` e **abrir as imagens**,
do mesmo jeito que a etapa 5 manda abrir os PNG dos gráficos. Sem Word instalado, o
LibreOffice em modo `--headless --convert-to pdf` serve.

O que procurar: palavra partida no meio, coluna que não respeita a proporção declarada,
linha de tabela dividida entre duas páginas, cabeçalho que não repete na continuação.

## Custo e escolha de modelo

Coleta, gráficos, DOCX e teste de sinais são scripts: custo zero de modelo. O gasto está
em ler evidências, cruzar e redigir, e é aí que está o valor — **não delegar isso a modelo
mais fraco**. Delegação só se paga em dois lugares, e só com volume: descrever os
argumentos de VM da seção 8 (lookup mecânico em `argumentos-wildfly.md`) e conferir os
números do documento contra o JSON.

Ordem de grandeza de uma análise completa, medida: ~4 mil deste arquivo, ~1,8 mil do
`resumo.md`, ~3 mil de `--o tudo`, mais os references que a análise pedir. **A escavação
manual do zip é o que estoura o orçamento** — numa análise real custou ~24 mil tokens
sozinha, e quase tudo o que ela buscava já sai dos recortes hoje.

## Cuidados

- **Dois formatos de cabeçalho no mesmo pacote.** O `stdout` não tem data na linha; ela
  vem do nome do arquivo e vira o dia quando a hora retrocede. `fontes-pacote-log.md`.
- **Linha de log ≠ entrada de log.** Stacktrace é continuação; num pacote observado, 85%
  das linhas eram continuação.
- **Contagem de exceção ≠ contagem de incidente.** Reportar ocorrências **e** a janela.
- **`threads.dump` é uma foto.** Corrobora; não prova contenção sustentada.
- **O bloco do monitor não tem horário.** `##ID_n##` é sequencial, não relógio: nada de
  cruzar com o pico de erro do `server.log` como se fosse a mesma janela.
- **`Params:` é dado do cliente.** O coletor guarda a quantidade, nunca o valor, e o teste
  de regressão falha se vazar. No documento não entra parâmetro em hipótese nenhuma.
- **`Runtime-info` cobre pouco.** Num pacote medido, 553 blocos de 16.013. A origem dos
  outros vem da pilha do `Monitor_Processos.log` — analisar só o `Monitor_Consulta.log`
  deixa 96% das consultas sem dono.
- **`BackgroundProcessSP` não é execução em background.** É o serviço que a tela chama para
  acompanhar o processo, e roda na requisição do usuário.
- **Driver carregado não é o banco em uso.** Ambiente Oracle com o driver de SQL Server no
  deploy é comum. Script do dialeto errado é pior que script nenhum: o cliente executa,
  recebe erro de sintaxe e passa a duvidar do documento inteiro.
- **Nome de argumento não é evento.** `-XX:+HeapDumpOnOutOfMemoryError` na linha de
  argumentos já virou "estouro de memória", e `epoll.hang.log = false` virou "trava de
  IO". `P_LINHA_CONFIG` corta eco de configuração antes dos sinais; ao acrescentar sinal
  novo, conferir se ele sobrevive a isso.
- **`Memoria Heap: X / Y` não é uso quando Xms = Xmx.** A VM reserva a heap inteira na
  subida, e a razão dá 100% em todo pacote bem configurado. Quem mede pressão de memória é
  `diagnostico.gc_pct`.
- **`total` de serviços na subida inclui os sob demanda.** Não subtrair de `iniciados` para
  achar os falhos: num pacote real a subtração dava 534 contra os 36 declarados.
- **Encoding do comentário do zip difere do resto do pacote.** Log em ISO-8859-1,
  comentário em UTF-8. Decodificar tudo igual quebrava só os campos acentuados, e por isso
  passou muito tempo sem aparecer.
- **DOCX aberto no Word** → gravação falha com `EBUSY`.
- Todo `ImageRun` precisa de `type: "png"`. Sem isso o Word abre com "arquivo corrompido"
  e o `validate.py` **passa mesmo assim**.
- **Não guardar dado real de cliente na skill.** `examples/` é genérico.
- O pacote é dado de produção: não subir para serviço externo nem publicar.

## Recursos

`scripts/`: `coletar_metricas.py` (coletor do pacote de log), `coletar_monitor.py` (pacote
do monitor e pontuação), `consultar.py` (recortes), `extrair_objetos.py` (entidade,
serviço, URI e quadros de pilha por assinatura, ver 2.1), `gerar_graficos.py` (regras de
visualização no cabeçalho), `gerar-diagnostico-docx.js` (DOCX DSTECH v.3),
`testar_sinais.py` (regressão dos detectores).

`references/`: `estrutura-documento.md` (seções e regras de conteúdo),
`catalogo-gargalos.md` (limiares e o que cada evidência não prova), `fontes-pacote-log.md`
(formato de cada fonte), `schema-diagnostico.md` (schema do JSON e campos do humanizer),
`checklist-service-desk.md` (roteiro oficial), `argumentos-wildfly.md`,
`baseline-wildfly23.md` + `baseline-wildfly23/`, `drivers-jdbc.md`,
`questionario-lentidao.md`, `scripts-sql/` + `scripts-sql/catalogo.json` (pergunta →
script por dialeto, lido pelo coletor).
