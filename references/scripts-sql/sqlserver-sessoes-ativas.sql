-- Sessoes de usuario em execucao, com o comando e o tempo decorrido.
-- Equivalente de oracle-sessoes-ativas.sql para SQL Server.
-- ATENCAO: script autoral da skill, nao homologado pelo Service Desk Sankhya.
-- Somente leitura. Requer VIEW SERVER STATE.

SELECT s.session_id                       AS sessao,
       r.status,
       s.login_name                       AS usuario_banco,
       s.host_name                        AS maquina,
       s.program_name                     AS programa,
       r.command                          AS comando_tipo,
       r.wait_type                         AS tipo_espera,
       r.wait_time                         AS espera_ms,
       r.total_elapsed_time                AS decorrido_ms,
       r.cpu_time                          AS cpu_ms,
       r.logical_reads                     AS leituras_logicas,
       r.writes                            AS escritas,
       r.blocking_session_id               AS bloqueado_por,
       SUBSTRING(t.text,
                 (r.statement_start_offset / 2) + 1,
                 ((CASE r.statement_end_offset
                        WHEN -1 THEN DATALENGTH(t.text)
                        ELSE r.statement_end_offset
                   END - r.statement_start_offset) / 2) + 1)
                                           AS comando,
       s.client_interface_name             AS interface,
       CONVERT(VARCHAR(19), s.login_time, 120) AS inicio_sessao
FROM sys.dm_exec_requests   r
JOIN sys.dm_exec_sessions   s ON s.session_id = r.session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) t
WHERE s.is_user_process = 1
  AND r.session_id <> @@SPID
ORDER BY r.total_elapsed_time DESC;
