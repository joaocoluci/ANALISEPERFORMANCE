# Checklist de problemas de performance — Service Desk

Destilado do documento oficial *Checklist de problemas de performance — Service Desk*
(Sankhya). É o roteiro que organiza a análise: primeiro enquadrar o tipo de lentidão,
depois percorrer a lista do tipo correspondente.

Os limiares numéricos daqui alimentam `catalogo-gargalos.md` e o coletor.

## Antes de tudo — entrevista

Os sintomas são melhor detalhados pelo usuário. O documento recomenda entrevistar quem
sente a lentidão, ou pedir demonstração por conexão remota, antes de partir para o log.
Perguntas em `questionario-lentidao.md`.

Quando a demanda for encaminhada para Unidade ou DBA da Central, **todos os arquivos
analisados — obrigatoriamente o log do sistema — vão anexados à OS**. Sem isso, o próximo
analista recoleta tudo.

## Verificações iniciais — antes de investigar

Melhorias que bases antigas não receberam e que devem estar em dia:

**Oracle**
- Criar índices para colunas de chave estrangeira sem índice — causa contenção.
  Script: `scripts-sql/oracle-indices-fk.sql`.

**SQL Server**
- `SNAPSHOT_ISOLATION_STATE` deve estar ligado e `IS_READ_COMMITTED_SNAPSHOT_ON` = 1.
  Vindo `OFF` e `0`, acionar DBA para ajustar.
- `AllowPageLocks` dos índices deve ser `FALSE` e `Lock Escalation` das tabelas `DISABLE`.
  Vindo `TRUE` e `TABLE`, ajustar.

**Em todos os casos**
- Memória do WildFly compatível com o porte e a quantidade de usuários.
- **Xms e Xmx com o mesmo valor.**
- Memória muito alta pode causar congelamento durante a coleta de lixo.
- **Serviços de TESTE e TREINA parados** quando não estiverem em uso.

## Lentidão generalizada

Todos os usuários, todas as rotinas. Em geral, máquina ou banco.

| Item | Verificação | Limiar |
|---|---|---|
| a | A lentidão está no servidor de aplicação ou de banco? A máquina é exclusiva do sistema? | — |
| b | Servidores atendem aos requisitos mínimos para a quantidade de usuários contratados? | documentação de requisitos |
| c | Consumo de CPU (`top` / Gerenciador de Tarefas) | **acima de 80%** é problema |
| d | Consumo de memória e uso de swap | swap em uso = memória insuficiente ou vazamento |
| e | Rede: `ping -s 1024` (Linux) ou `ping -t -l 1024` (Windows) | **máx. 0,5 ms** em rede 10/100/1000 |
| f | Disco: `winsat disk -drive c:` ou `dd` | **mín. 120 MB/s** sequencial |
| g | Sessões ativas no banco | `oracle-sessoes-ativas.sql` / Activity Monitor |
| i | Bloqueios longos | `oracle-bloqueios.sql` / Head Blocker |
| j | Mensagens de erro intermitentes no log | procurar `Exception`, `Caused by`, `ORA-` |
| k | Relatório de diagnóstico do log | conexões perto do máximo do pool; CPU e GC altos |
| l | Estatísticas de DML | ver limiares abaixo |
| m | Argumentos do WildFly | ver `argumentos-wildfly.md` |

Nos itens c, d, e e f o documento manda verificar também **processos estranhos** no
servidor — o exemplo citado é minerador de criptomoeda.

No item j: erro decorrente de regra do cliente é o cliente que resolve; erro de sistema vai
para DBA ou suporte. `ORA-00060` e `ORA-01013` no Oracle, e mensagens de deadlock ou
timeout no SQL Server, são apontados como relacionados a lentidão.

### Item l — estatísticas de DML

Geradas pelo `extratorDML.jar`, executado na mesma pasta do log:

```
java -jar extratorDML.jar server.log_20190812144947.zip
```

O pacote de coleta já traz `dml_stats/` pronto — o extrator só é necessário quando o
pacote não os contém.

**Tempos médios de referência:**

| Objeto | INSERT | UPDATE | DELETE | STP |
|---|---:|---:|---:|---:|
| TGFCAB | 200 ms | 100 ms | 350 ms | — |
| TGFITE | 200 ms | 100 ms | 200 ms | — |
| TGFFIN | 150 ms | 100 ms | 200 ms | — |
| STP_CONFIRMANOTA2 | — | — | — | 300 ms |
| STP_NUMERAR_NOTA2 | — | — | — | 200 ms |
| STP_SET_SESSION | — | — | — | 10 ms |

Elevação de **até 20%** é aceitável. Os valores podem subir legitimamente com alto volume
de personalizações, principalmente em TGFCAB e TGFITE.

Muito acima disso: verificar objetos personalizados — gatilhos, eventos, etc. Em procedures,
observar quantidade de execuções e tempo total, sobretudo nas personalizadas; muito altos,
revisar a rotina que as aciona.

**Atenção especial a DELETE:** comandos de exclusão são apontados como causadores
frequentes de contenção.

### Item m — parâmetros do WildFly

Verificar nos "Argumentos da VM" registrados no log:
- timeout de query, sessão e transação;
- numeração por procedure e a lista de tabelas que a usam;
- commit type B;
- tamanho do pool de conexões contra o uso do cliente.

### Conclusões do tipo generalizada

- Requisito de hardware não atendido → TI do cliente.
- Sessão ativa ou lock cujo objeto é personalizado → autor da customização.
  Objeto padrão → verificar se é falha de implementação.
- Sem causa identificada → DBA da Unidade ou da Central.

## Lentidão localizada

Uma tela, rotina ou módulo. Geralmente sistema, parametrização ou um ponto específico do banco.

| Item | Verificação |
|---|---|
| a | A rotina lenta é personalizada? Se sim, coletar logs e monitor de consulta e encaminhar a quem a criou |
| b | O mesmo procedimento é lento nas bases de teste? Reproduzir passo a passo como o cliente faz |
| c | A tarefa termina, mas devagar? Procurar consulta lenta no Monitor de Consultas |
| d | Há mensagem de timeout? Identificar **qual** dos três timeouts |
| e | Não há query lenta e o sistema não responde? Verificar CPU, memória e rede; testar reinício |

### Item c — regex de consulta lenta

No Monitor de Consultas, com expressão regular:

```
##ID_[0-9]{0,6}## tempo: [0-9]{3,10}      → acima de 100 ms
##ID_[0-9]{0,6}## tempo: [0-9]{4,10}      → acima de 1 segundo
```

Depois, comparar o plano de execução da consulta lenta com o de outras bases.

### Item d — os três timeouts

Query, sessão e transação são coisas diferentes. Ponto do documento que mais se erra:

> "Considere o somatório dos tempos de execução das consultas. Pode ser que elas estejam
> rápidas, mas a rotina executa milhares de consultas de uma só vez."

Timeout de sessão ou transação com consultas individualmente rápidas é o padrão, não a
exceção. Concluir "consulta lenta" a partir dele é erro.

## Lentidão em horários específicos

Aparece e some. Preferencialmente, analisar durante a ocorrência.

| Item | Verificação |
|---|---|
| a | Backup ou processo agendado no SO / banco naquele horário? |
| b | Ações agendadas no sistema (Configurações » Avançado » Ações Agendadas)? |
| c | Rotina pesada com grande massa de dados? Relatório, dashboard ou rotina personalizada? |
| d | Integração ou carga de dados via webservice ou direto no banco? |

Tabelas para checar no item c: `TSIARF` (agendamento de relatórios formatados),
`TSIAAG` (ações agendadas), `TGFTAG` (tarefas agendadas), `TSICND` (consolidador de dados).

No item d, observar no log a repetição de termo ou nome de integração no horário relatado.
