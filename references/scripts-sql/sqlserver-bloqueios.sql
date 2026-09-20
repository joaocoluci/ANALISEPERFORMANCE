-- Sessoes bloqueadas, a sessao bloqueadora e o comando das duas pontas.
-- Equivalente de oracle-bloqueios.sql para SQL Server.
-- ATENCAO: script autoral da skill, nao homologado pelo Service Desk Sankhya.
-- Somente leitura. Requer VIEW SERVER STATE.
-- Nenhuma linha significa que nao ha bloqueio no instante da execucao.

SELECT r.blocking_session_id              AS sessao_bloqueadora,
       sb.login_name                      AS usuario_bloqueador,
       sb.host_name                       AS maquina_bloqueadora,
       sb.program_name                    AS programa_bloqueador,
       tb.text                            AS comando_bloqueador,
       r.session_id                       AS sessao_bloqueada,
       s.login_name                       AS usuario_bloqueado,
       s.host_name                        AS maquina_bloqueada,
       r.wait_type                        AS tipo_espera,
       r.wait_time                        AS espera_ms,
       r.wait_resource                    AS recurso,
       SUBSTRING(t.text,
                 (r.statement_start_offset / 2) + 1,
                 ((CASE r.statement_end_offset
                        WHEN -1 THEN DATALENGTH(t.text)
                        ELSE r.statement_end_offset
                   END - r.statement_start_offset) / 2) + 1)
                                          AS comando_bloqueado
FROM sys.dm_exec_requests   r
JOIN sys.dm_exec_sessions   s  ON s.session_id  = r.session_id
LEFT JOIN sys.dm_exec_sessions sb ON sb.session_id = r.blocking_session_id
OUTER APPLY sys.dm_exec_sql_text(r.sql_handle) t
OUTER APPLY (SELECT TOP (1) st.text
             FROM sys.dm_exec_connections c
             CROSS APPLY sys.dm_exec_sql_text(c.most_recent_sql_handle) st
             WHERE c.session_id = r.blocking_session_id) tb
WHERE r.blocking_session_id <> 0
ORDER BY r.wait_time DESC;
