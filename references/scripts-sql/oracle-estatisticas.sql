-- Data da última coleta de estatísticas por tabela.
-- Origem: Checklist de problemas de performance - Service Desk Sankhya.

SELECT TABLE_NAME,
LAST_ANALYZED,
NUM_ROWS
FROM USER_TABLES
WHERE NUM_ROWS > 0
ORDER BY NUM_ROWS DESC;
