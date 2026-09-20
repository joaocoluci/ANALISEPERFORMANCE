-- Configuracoes de base que o checklist de performance exige em SQL Server.
-- ATENCAO: script autoral da skill, nao homologado pelo Service Desk Sankhya.
-- Somente leitura. Rodar conectado a base do Sankhya, nao a master.
--
-- Esperado pelo checklist:
--   SNAPSHOT_ISOLATION      = ON
--   READ_COMMITTED_SNAPSHOT = 1
--   AllowPageLocks          = FALSE  (consulta 2 sem nenhuma linha)
--   Lock Escalation         = DISABLE (consulta 3 sem nenhuma linha)
-- Vindo diferente, acionar o DBA. Nenhum dos tres se ajusta sem janela.

-- 1. Estado da base
SELECT DB_NAME()                        AS base,
       snapshot_isolation_state_desc    AS snapshot_isolation,
       is_read_committed_snapshot_on    AS read_committed_snapshot,
       recovery_model_desc              AS modelo_recuperacao,
       is_auto_create_stats_on          AS cria_estatistica_automatico,
       is_auto_update_stats_on          AS atualiza_estatistica_automatico,
       is_auto_update_stats_async_on    AS atualiza_estatistica_assincrono,
       compatibility_level              AS nivel_compatibilidade
FROM sys.databases
WHERE database_id = DB_ID();

-- 2. Indices com bloqueio de pagina permitido. Esperado: nenhuma linha.
SELECT OBJECT_SCHEMA_NAME(i.object_id) AS esquema,
       OBJECT_NAME(i.object_id)        AS tabela,
       i.name                          AS indice,
       i.type_desc                     AS tipo
FROM sys.indexes i
WHERE i.allow_page_locks = 1
  AND i.type IN (1, 2)
  AND OBJECTPROPERTY(i.object_id, 'IsUserTable') = 1
ORDER BY 1, 2, 3;

-- 3. Tabelas com escalonamento de bloqueio ativo. Esperado: nenhuma linha.
SELECT OBJECT_SCHEMA_NAME(t.object_id) AS esquema,
       t.name                          AS tabela,
       t.lock_escalation_desc          AS lock_escalation
FROM sys.tables t
WHERE t.lock_escalation_desc <> 'DISABLE'
ORDER BY 1, 2;
