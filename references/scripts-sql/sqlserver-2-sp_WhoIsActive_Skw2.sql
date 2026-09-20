-- Vincula sessão do SQL Server ao CODUSU e à thread do Sankhya.
-- Origem: Checklist de problemas de performance - Service Desk Sankhya.

CREATE PROCEDURE sp_WhoIsActive_Skw2 AS
BEGIN
IF OBJECT_ID('tempdb..#tempWhoIsActive') IS NOT NULL DROP TABLE #tempWhoIsActive
CREATE TABLE #tempWhoIsActive (
[dd hh:mm:ss.mss] varchar NULL,
[session_id] [smallint] NOT NULL,
[sql_text] [xml],
[sql_command] [xml],
[login_name] varchar,
[wait_info] varchar,
[cpu] varchar,
[tempdb_allocations] varchar,
[tempdb_current] varchar,
[blocking_session_id] varchar,
[reads] varchar,
[writes] varchar,
[physical_reads] varchar,
[used_memory] varchar,
[status] varchar,
[open_tran_count] varchar,
[percent_complete] varchar,
[host_name] varchar,
[database_name] varchar,
[program_name] varchar,
[start_time] [datetime],
[login_time] [datetime],
[request_id] varchar,
[collection_time] [datetime]
)
EXEC sp_WhoIsActive @destination_table = '#tempWhoIsActive',
@output_column_list = '[dd%][session_id][sql_text][sql_command][login_name][wait_info][cpu][tempdb_allocations][tempdb_current][blocking_session_id][reads][writes][physical_reads][used_memory][status][open_tran_count][percent_complete]
[host_name][database_name][program_name][start_time][login_time][request_id][collection_time]',
@get_outer_command=1
SELECT
CASE
WHEN LTRIM(RTRIM(CAST(s.CONTEXT_INFO AS varchar(max)))) IS NOT NULL THEN LTRIM(RTRIM(SUBSTRING(
CAST(s.CONTEXT_INFO AS varchar(max)),
CHARINDEX('u= ', CAST(s.CONTEXT_INFO AS varchar(max))) + 3,
ABS((CHARINDEX(',', CAST(s.CONTEXT_INFO AS varchar(max)), 0)) - (CHARINDEX('u= ', CAST(s.CONTEXT_INFO AS varchar(max))) + 3))
)))
ELSE ''
END AS CODUSU,
CASE
WHEN LTRIM(RTRIM(CAST(s.CONTEXT_INFO AS varchar(max)))) IS NOT NULL THEN LTRIM(RTRIM(SUBSTRING(
CAST(s.CONTEXT_INFO AS varchar(max)),
CHARINDEX('t_name= ', CAST(s.CONTEXT_INFO AS varchar(max))) + 8,
ABS(LEN(CAST(s.CONTEXT_INFO AS varchar(max))) - CHARINDEX('t_name= ', CAST(s.CONTEXT_INFO AS varchar(max))) + 8)
)))
ELSE ''
END AS THREAD,
t.*, CAST(s.CONTEXT_INFO AS varchar(max)) AS SKWINFO
FROM #tempWhoIsActive t
INNER JOIN sysprocesses s
ON t.session_id = s.spid
DROP TABLE #tempWhoIsActive
END
