rem ### -*- batch file -*- ######################################################
rem #                                                                          ##
rem #  JBoss Bootstrap Script Configuration                                    ##
rem #                                                                          ##
rem #############################################################################

rem # $Id: run.conf.bat 88820 2009-05-13 15:25:44Z dimitris@jboss.org $

rem #
rem # This batch file is executed by run.bat to initialize the environment
rem # variables that run.bat uses. It is recommended to use this file to
rem # configure these variables, rather than modifying run.bat itself.
rem #

rem Uncomment the following line to disable manipulation of JAVA_OPTS (JVM parameters)
rem set PRESERVE_JAVA_OPTS=true

if not "x%JAVA_OPTS%" == "x" (
  echo "JAVA_OPTS already set in environment; overriding default settings with values: %JAVA_OPTS%"
  goto JAVA_OPTS_SET
)

rem #
rem # Specify the JBoss Profiler configuration file to load.
rem #
rem # Default is to not load a JBoss Profiler configuration file.
rem #
rem set "PROFILER=%JBOSS_HOME%\bin\jboss-profiler.properties"

rem #
rem # Specify the location of the Java home directory (it is recommended that
rem # this always be set). If set, then "%JAVA_HOME%\bin\java" will be used as
rem # the Java VM executable; otherwise, "%JAVA%" will be used (see below).
rem #
rem set "JAVA_HOME=C:\opt\jdk1.6.0_23"

rem #
rem # Specify the exact Java VM executable to use - only used if JAVA_HOME is
rem # not set. Default is "java".
rem #
rem set "JAVA=C:\opt\jdk1.6.0_23\bin\java"

rem #
rem # Specify options to pass to the Java VM. Note, there are some additional
rem # options that are always passed by run.bat.
rem #

rem # JVM memory allocation pool parameters - modify as appropriate.
REM ### Limpamos o JAVA_OPTS por que a reinicialização do WPM chama novamente este ###

 set "JBOSS_MODULES_SYSTEM_PKGS=org.jboss.byteman"

 set "JAVA_OPTS=-Djboss.socket.binding.port-offset=0 -Djboss.bind.address=0.0.0.0"

 set "JAVA_OPTS=%JAVA_OPTS% -Xms1024m -Xmx2048m"

 REM DEGUB
 REM set DEBUG_PORT=8787
 REM SET %JAVA_OPTS% -agentlib:jdwp=transport=dt_socket,address=%DEBUG_PORT%,server=y,suspend=n

 set "JAVA_OPTS=%JAVA_OPTS% -Duser.language=pt -Duser.country=BR -Dfile.encoding=ISO-8859-1"

 set "JAVA_OPTS=%JAVA_OPTS% -Djava.util.Arrays.useLegacyMergeSort=true -Djboss.node.name=master"

 set "JAVA_OPTS=%JAVA_OPTS% -Djava.net.preferIPv4Stack=true"

 set "JAVA_OPTS=%JAVA_OPTS% -Djboss.modules.system.pkgs=%JBOSS_MODULES_SYSTEM_PKGS% -Djava.awt.headless=true"

 set "JAVA_OPTS=%JAVA_OPTS% -Dcom.arjuna.ats.arjuna.allowMultipleLastResources=true -Dcom.arjuna.ats.coordinator.afterCompletion.reverse.order=false"

 set "JAVA_OPTS=%JAVA_OPTS% -Depoll.hang.log=false -Depoll.hang.timeout=180000 -Djboss.as.management.blocking.timeout=3600"

 set "JAVA_OPTS=%JAVA_OPTS% -XX:+UseG1GC"
 
 set "JAVA_OPTS=%JAVA_OPTS% -Djava.naming.factory.initial=org.sankhya.wildfly.jndi.NamingInitialContextFactory"

 set "JAVA_OPTS=%JAVA_OPTS% -Djava.net.preferIPv4Stack=true -Dsun.security.ssl.allowUnsafeRenegotiation=true"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.cancel.previous.identified.session=false"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.experimental.always.reuse.jdbc.conn=true -Djape.experimental.commit-type=B -Djape.experimental.lock.strategy=1"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.global.query.timeout=600 -Djape.jdbc.check.select=true -Djape.jdbc.monitor.enabled=true"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.jdbc.monitor.kill.thread.wait=10000 -Djape.jdbc.monitor.timeout.tolerance=20000 -Djape.lazy.init=true"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.lob.fields.as.lazy=true -Djape.mysql.lowercase=true -Djape.session.timeout=1800000"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.use.connection.recorder=false"
 
 set "JAVA_OPTS=%JAVA_OPTS% -Djape.use.write.history=false -Dskw.uid-gen.strategy=3"

 set "JAVA_OPTS=%JAVA_OPTS% -Djape.sqlserver.use.native.query.getpk=true -Dskw.consulta.produtos.sql_ci_ai=true"

:JAVA_OPTS_SET

rem # Uncomment to add a Java agent. If an agent is added to the module options, then jboss-modules.jar is added as an agent
rem # on the JVM. This allows things like the log manager or security manager to be configured before the agent is invoked.
rem set "MODULE_OPTS=-javaagent:agent.jar"
