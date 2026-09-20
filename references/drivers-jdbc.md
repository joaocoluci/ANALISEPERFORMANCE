# Drivers JDBC

O driver é o componente de menor risco de atualização do ambiente e o mais esquecido.
Correções de desempenho, de vazamento de cursor e de tratamento de tipo chegam por ele, sem
tocar em aplicação nem em banco.

## Onde o pacote de coleta mostra o driver

Duas fontes, e vale cruzar:

**Log de inicialização.** O WildFly registra cada driver que carrega, com a versão que o
próprio driver declara:

```
WFLYJCA0004: Deploying JDBC-compliant driver class oracle.jdbc.OracleDriver (version 19.23)
WFLYJCA0004: Deploying JDBC-compliant driver class com.microsoft.sqlserver.jdbc.SQLServerDriver (version 4.1)
WFLYJCA0004: Deploying JDBC-compliant driver class net.sourceforge.jtds.jdbc.Driver (version 1.3)
WFLYJCA0004: Deploying JDBC-compliant driver class org.h2.Driver (version 1.4)
```

**`mge-ds.xml`.** Diz qual driver o datasource realmente usa (`<driver>`), que é um só. Os
demais estão carregados sem uso.

Cuidado ao ler o `mge-ds.xml`: `<driver-class>` e `<driver>` são tags diferentes, e um regex
frouxo faz uma casar com a outra.

## Versão do banco

Aparece no log quando o driver registra o banner:

```
Oracle Database 19c EE Extreme Perf Release 19.0.0.0.0 - Production
```

Nem todo pacote traz. Sem o banner, a versão do banco fica como verificação a fazer, e a
comparação driver/banco não se sustenta. Não inferir a versão do banco a partir da versão do
driver: são independentes, e é justamente o desencontro entre elas que se está procurando.

## Regra de compatibilidade

O driver deve ser **igual ou mais novo** que o banco. Driver mais novo que o banco funciona e
é a situação recomendada pelos dois fabricantes; driver mais antigo que o banco perde recurso
e, em alguns casos, falha em tipo de dado novo.

### Oracle

O `ojdbc` acompanha a versão do banco: `ojdbc8` para Java 8, `ojdbc11` para Java 11 ou
superior. A versão do JAR (19.x, 21.x, 23.x) indica a versão do banco para a qual foi
compilado, e a Oracle mantém compatibilidade retroativa ampla.

| Banco | Driver adequado |
|---|---|
| Oracle 19c | 19.x ou superior |
| Oracle 21c | 21.x ou superior |
| Oracle 23ai | 23.x |

O pacote de referência do WildFly 23 traz **19.26.0.0.0**. Um cliente em 19.23 está na mesma
linha, atrás em correções. É recomendação de baixa severidade: vale fazer, não é a causa de
lentidão. Afirmar que a atualização do driver resolve um gargalo de banco é erro de leitura.

### SQL Server: usar o driver da Microsoft

Existem dois caminhos no ecossistema Sankhya, e o pacote de referência traz os dois módulos
declarados:

| Módulo | Driver | Situação |
|---|---|---|
| `custom.sqljdbc` | `com.microsoft.sqlserver.jdbc.SQLServerDriver` | **o recomendado** |
| `custom.jtds` | `net.sourceforge.jtds.jdbc.Driver` | legado |

**Para SQL Server, a recomendação é o driver oficial da Microsoft (`mssql-jdbc`).** O jTDS é
projeto de terceiros cuja última versão, 1.3.1, é de 2013. Ele não acompanha os recursos do
SQL Server das versões seguintes, não recebe correção de segurança e não tem suporte do
fabricante do banco.

Ao encontrar jTDS em uso, a recomendação carrega o que a troca exige, e não só a troca:

- a URL de conexão muda de formato (`jdbc:jtds:sqlserver://…` para `jdbc:sqlserver://…`);
- o `mge-ds.xml` passa a apontar o outro módulo;
- comportamento de tipo de dado e de fuso pode mudar, o que pede validação das rotinas que
  gravam data e hora;
- exige janela de parada.

Sem esses pontos, a recomendação parece trivial e o cliente a executa sem validar.

**Atenção à versão do módulo `sqljdbc` do próprio pacote de referência:** o JAR empacotado
declara `Microsoft JDBC Driver 4.1`, de 2015. Recomendar "trocar jTDS pelo driver da
Microsoft" e deixar o cliente com o 4.1 troca um driver antigo por outro. A recomendação
completa é usar o `mssql-jdbc` na versão compatível com o SQL Server do cliente e com o Java
do servidor de aplicações, substituindo o JAR do módulo.

| SQL Server | `mssql-jdbc` | Observação |
|---|---|---|
| 2016 e superior | versão atual da linha suportada | escolher o artefato `jre8` ou `jre11` conforme o Java do servidor |
| 2012 / 2014 | verificar a matriz da Microsoft antes | linhas recentes do driver deixaram de suportar bancos antigos |

A matriz de suporte é publicada pela Microsoft e muda com o tempo. **Verificar na
documentação do fabricante no momento da análise**, em vez de fixar um número aqui que
envelhece sem aviso.

### MySQL

O pacote de referência traz o Connector/J **8.0.30**. A classe do driver mudou de
`com.mysql.jdbc.Driver` para `com.mysql.cj.jdbc.Driver` na versão 8; encontrar a classe
antiga indica driver anterior à 8.

## Driver a mais carregado

O WildFly carrega todos os módulos de driver declarados, mesmo os que nenhum datasource usa.
Cada um custa memória e tempo na subida. Um ambiente Oracle com jTDS, `sqljdbc` e MySQL
carregados tem três drivers inúteis no processo.

É apontamento de baixa severidade: arrumar é limpeza, não ganho de desempenho mensurável. Vale
mencionar junto com os outros itens de configuração, não como gargalo.

## Módulo com JAR inválido

```
jtds-1.2-master.jar  does not point to a valid jar for a Class-Path reference
```

O módulo declara um JAR que não existe ou está corrompido. Efeito imediato nenhum, se o banco
correspondente não é usado. Mas a mensagem aparece a cada inicialização, e um módulo quebrado
que ninguém percebeu costuma indicar migração antiga incompleta. Corrigir o `module.xml` ou
remover o módulo.

## Ordem das recomendações de driver

Nenhum item desta página é causa de lentidão sentida pelo usuário. Todos entram como
higiene de ambiente, depois dos gargalos com efeito medido. A exceção é o jTDS em ambiente
SQL Server com problema de tipo de dado ou de fuso, onde o driver deixa de ser higiene e
passa a ser causa.
