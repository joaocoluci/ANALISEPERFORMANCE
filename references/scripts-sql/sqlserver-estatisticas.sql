-- Data da ultima coleta de estatisticas por tabela, com o volume de linhas.
-- Equivalente de oracle-estatisticas.sql para SQL Server.
-- ATENCAO: script autoral da skill, nao homologado pelo Service Desk Sankhya.
-- Somente leitura. Requer SQL Server 2008 R2 SP2 ou superior
-- (sys.dm_db_stats_properties).
--
-- Leitura: MODIFICACOES_DESDE_A_COLETA alto em tabela grande indica
-- estatistica velha, e plano de execucao decidido sobre volume errado.

SELECT OBJECT_SCHEMA_NAME(st.object_id)        AS esquema,
       OBJECT_NAME(st.object_id)               AS tabela,
       st.name                                 AS estatistica,
       CONVERT(VARCHAR(19), sp.last_updated, 120) AS ultima_coleta,
       DATEDIFF(DAY, sp.last_updated, GETDATE()) AS dias_desde_a_coleta,
       sp.rows                                 AS linhas,
       sp.rows_sampled                         AS linhas_amostradas,
       sp.modification_counter                 AS modificacoes_desde_a_coleta
FROM sys.stats st
CROSS APPLY sys.dm_db_stats_properties(st.object_id, st.stats_id) sp
WHERE OBJECTPROPERTY(st.object_id, 'IsUserTable') = 1
  AND sp.rows > 0
ORDER BY sp.rows DESC;
