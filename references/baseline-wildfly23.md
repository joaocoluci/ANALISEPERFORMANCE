# Pacote de referência: WildFly 23.0 Sankhya mod 05

Configuração de referência para comparar com o ambiente do cliente. Os arquivos vivem em
`baseline-wildfly23/` e foram extraídos do pacote de instalação `Wildfly_23.0_Sankhya_mod_05.zip`
distribuído pela Sankhya, já com os ajustes de produção aplicados.

| Arquivo | Origem no pacote |
|---|---|
| `standalone.conf` | `wildfly_producao/bin/standalone.conf` (Linux) |
| `standalone.conf.bat` | `wildfly_producao/bin/standalone.conf.bat` (Windows) |
| `standalone.xml` | `wildfly_producao/standalone/configuration/standalone.xml` |

Para atualizar a comparação quando sair uma versão nova do pacote, basta substituir esses
três arquivos e ajustar `BASELINE_VERSAO` e `DRIVERS_BASELINE` no coletor.

## O que o coletor compara e o que ele deixa de fora

A comparação separa os argumentos em cinco listas. A separação existe porque tratar tudo
como desvio produz uma lista longa e desacreditada:

| Lista | O que é | Como tratar no documento |
|---|---|---|
| `ausentes` | está no baseline, não está no cliente | avaliar um por um |
| `ausentes_condicionais` | ausente por depender de banco ou sistema operacional que o cliente não usa | mencionar só se relevante; não é desvio |
| `divergentes` | presente nos dois, com valor diferente | avaliar um por um |
| `dimensionamento` | `-Xms`, `-Xmx`, `-Xss`, metaspace, memória direta | **nunca chamar de desvio**, ver abaixo |
| `extras` | está no cliente, não no baseline | pode ser funcionalidade legítima ou herança |

Ficam fora da comparação os argumentos de endereço, porta, caminho e credencial, e os que o
próprio script de inicialização injeta (`logging.configuration`, `org.jboss.boot.log.file`,
`program.name`).

## Memória: o baseline não é recomendação de porte

O baseline traz `-Xms1024m -Xmx2048m`. **Esses são os valores de partida da instalação, não
o valor recomendado para o ambiente do cliente.** Um cliente com mais usuários deve ter mais
memória, e o próprio checklist do Service Desk manda dimensionar pelo porte e pela quantidade
de usuários.

Reportar "memória divergente do recomendado" porque o cliente tem 5 GB contra 2 GB do
baseline seria errado e o cliente perceberia. O que se aponta em memória é outra coisa:

- **mínimo diferente do máximo** (regra explícita do checklist, e o baseline também não a
  cumpre, ver contradição abaixo);
- **uso próximo do teto** no instante da coleta;
- **coletor inadequado** para o tamanho da área.

### Contradição entre as duas fontes oficiais

O *Checklist de problemas de performance* pede mínimo e máximo iguais. O `standalone.conf`
do pacote de referência traz `1024m` e `2048m`, diferentes. As duas fontes são da Sankhya.

Como tratar: a recomendação de igualar vem do documento que trata de performance, e a razão
técnica é conhecida (expansão de área sob carga provoca pausa no pico). O baseline traz
valores de instalação genérica. **Recomendar igualar, no valor que o porte pedir, e não citar
a contradição no documento do cliente.** Registrar aqui para que ninguém a "descubra" depois
e mude a recomendação sem contexto.

## Argumentos do baseline que o WildFly 11 típico não tem

Os que mais aparecem como ausentes em ambiente antigo:

| Argumento | Efeito | Leitura |
|---|---|---|
| `-XX:+UseG1GC` | coletor G1 | o ambiente antigo costuma estar em `-XX:+UseConcMarkSweepGC`, e os dois aparecem juntos na comparação: G1 como ausente, CMS como extra |
| `-Dfile.encoding=ISO-8859-1` | codificação da JVM | sem ele a JVM usa o padrão do sistema. Em Windows brasileiro cai em `Cp1252`, próximo mas não idêntico. Afeta acentuação em arquivo gerado e em integração |
| `-Djava.util.Arrays.useLegacyMergeSort=true` | algoritmo de ordenação antigo | evita `IllegalArgumentException: Comparison method violates its general contract` em comparador inconsistente. Ausência é risco de erro, não de lentidão |
| `-Dskw.consulta.produtos.sql_ci_ai=true` | consulta de produto sem sensibilidade a caso e acento | comportamento de busca na tela de produtos |
| `-XX:-OmitStackTraceInFastThrow` | mantém rastreamento em exceção repetida | sem ele, exceção frequente perde a pilha e o diagnóstico fica cego |

## standalone.xml de referência

Pontos que valem comparação com o do cliente, quando ele estiver disponível (o pacote de
coleta **não** traz o `standalone.xml`, apenas o `mge-ds.xml`):

| Ponto | Valor de referência |
|---|---|
| Timeout de transação | `default-timeout="1800"` (30 min) |
| Codificação do Undertow | `url-charset` e `default-encoding` em `ISO-8859-1`, `jsp-config java-encoding="ISO-8859-1"` |
| Tamanho máximo de POST | `max-post-size="2147483648"` |
| Reuso de id de sessão | `disable-session-id-reuse="true"` |
| Estatísticas | desligadas por padrão, ligáveis por propriedade |
| Drivers declarados | `com.oracle.ojdbc`, `net.sourceforge.jtds`, `com.microsoft.sqljdbc`, `com.mysql.jdbc`, mais o `h2` interno |

## Recomendar a atualização para a versão 23

Quando o cliente estiver em versão anterior, a recomendação é legítima, mas **não é um ajuste
de configuração**: é substituição da instalação do servidor de aplicações. O que o documento
precisa dizer:

- o que se ganha: G1 já configurado, drivers atualizados, argumentos de JAPE consolidados e
  correções acumuladas do próprio WildFly entre a versão do cliente e a 23;
- o que a troca exige: migração da configuração atual, dos módulos personalizados e dos
  ajustes de `standalone.xml`, além de validação das integrações;
- que pede janela de parada e plano de retorno;
- que **não substitui** o tratamento dos gargalos de banco e de personalização. Trocar o
  servidor de aplicações não acelera uma procedure que leva 26 segundos.

O último ponto é o mais importante. Uma recomendação de upgrade colocada no topo da lista faz
o cliente acreditar que ela resolve o problema todo, e a frustração depois queima a análise
inteira. Severidade média, e posicionada depois dos gargalos com efeito medido.

## Java

O baseline roda em WildFly 23, que aceita Java 8 e Java 11. Ambiente em Java 8 com CMS tem
uma restrição encadeada: G1 funciona em Java 8, mas as opções de ajuste fino do G1 e os
coletores mais novos pedem Java 11 ou superior. Ao recomendar troca de coletor, dizer em qual
versão de Java a recomendação vale.
