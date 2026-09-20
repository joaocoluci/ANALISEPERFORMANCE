-- Chaves estrangeiras sem indice de apoio, e o comando de criacao de cada uma.
-- Equivalente de oracle-indices-fk.sql para SQL Server.
-- ATENCAO: script autoral da skill, nao homologado pelo Service Desk Sankhya.
--
-- DIFERENCA IMPORTANTE em relacao a versao Oracle: aqui o script apenas
-- GERA os comandos, na coluna COMANDO. Ele nao cria indice nenhum. Revise a
-- saida, confira nome repetido e execute em janela de manutencao.
--
-- Criterio: existe indice de apoio quando algum indice da tabela comeca pelas
-- mesmas colunas da chave estrangeira, na mesma ordem. Indice que contem as
-- colunas em outra posicao nao evita a contencao.

;WITH cols_fk AS (
    SELECT fkc.constraint_object_id AS fk_id,
           fkc.parent_object_id     AS tabela_id,
           fkc.constraint_column_id AS ordem,
           c.name                   AS coluna
    FROM sys.foreign_key_columns fkc
    JOIN sys.columns c
      ON c.object_id = fkc.parent_object_id
     AND c.column_id = fkc.parent_column_id
),
fk AS (
    SELECT f.fk_id,
           f.tabela_id,
           STUFF((SELECT ',' + QUOTENAME(x.coluna)
                  FROM cols_fk x
                  WHERE x.fk_id = f.fk_id
                  ORDER BY x.ordem
                  FOR XML PATH('')), 1, 1, '') AS lista_colunas,
           STUFF((SELECT ',' + x.coluna
                  FROM cols_fk x
                  WHERE x.fk_id = f.fk_id
                  ORDER BY x.ordem
                  FOR XML PATH('')), 1, 1, '') AS chave_fk,
           STUFF((SELECT '_' + x.coluna
                  FROM cols_fk x
                  WHERE x.fk_id = f.fk_id
                  ORDER BY x.ordem
                  FOR XML PATH('')), 1, 1, '') AS sufixo
    FROM cols_fk f
    GROUP BY f.fk_id, f.tabela_id
),
idx AS (
    SELECT i.object_id AS tabela_id,
           STUFF((SELECT ',' + c2.name
                  FROM sys.index_columns ic2
                  JOIN sys.columns c2
                    ON c2.object_id = ic2.object_id
                   AND c2.column_id = ic2.column_id
                  WHERE ic2.object_id = i.object_id
                    AND ic2.index_id  = i.index_id
                    AND ic2.is_included_column = 0
                  ORDER BY ic2.key_ordinal
                  FOR XML PATH('')), 1, 1, '') AS chave_idx
    FROM sys.indexes i
    WHERE i.type IN (1, 2)          -- clustered e nonclustered
)
SELECT OBJECT_SCHEMA_NAME(fk.tabela_id)       AS esquema,
       OBJECT_NAME(fk.tabela_id)              AS tabela,
       OBJECT_NAME(fk.fk_id)                  AS chave_estrangeira,
       fk.chave_fk                            AS colunas,
       'CREATE INDEX ' + QUOTENAME(LEFT(OBJECT_NAME(fk.tabela_id), 10)
           + 'IDX_FK' + LEFT(REPLACE(fk.sufixo, '_', ''), 10))
           + ' ON ' + QUOTENAME(OBJECT_SCHEMA_NAME(fk.tabela_id))
           + '.' + QUOTENAME(OBJECT_NAME(fk.tabela_id))
           + ' (' + fk.lista_colunas + ');' AS comando
FROM fk
WHERE OBJECT_NAME(fk.tabela_id) LIKE 'T%'
  AND NOT EXISTS (SELECT 1
                  FROM idx
                  WHERE idx.tabela_id = fk.tabela_id
                    AND idx.chave_idx LIKE fk.chave_fk + '%')
ORDER BY 1, 2, 3;
