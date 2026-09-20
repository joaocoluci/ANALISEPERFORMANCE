-- Sessões ACTIVE com o SQL em execução.
-- Origem: Checklist de problemas de performance - Service Desk Sankhya.

SELECT s.sid,
s.serial#,
s.status,
s.username,
s.machine,
s.osuser,
(SELECT sql_fulltext
FROM v$sql
WHERE sql_id = s.sql_id and rownum = 1) AS comando,
s.client_info
FROM V$PROCESS p,
v$session s
WHERE p.addr = s.paddr
AND s.status = 'ACTIVE'
AND s.username is not null;
