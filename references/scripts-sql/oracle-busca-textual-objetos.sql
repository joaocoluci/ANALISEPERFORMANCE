-- Procura um texto em procedures, dashboards, campos calculados e ações.
-- Origem: Checklist de problemas de performance - Service Desk Sankhya.

/* Ao executar, na IDE de banco preencha o campo BUSCA com o valor que deseja encontrar */
SELECT DISTINCT OBJECT_TYPE AS TIPO, OBJECT_NAME AS NOME
FROM USER_OBJECTS OBJ, USER_SOURCE SRC
WHERE SRC.NAME = OBJ.OBJECT_NAME
AND UPPER (SRC.TEXT) LIKE UPPER ('%' || :BUSCA || '%')
UNION ALL
SELECT DISTINCT 'DASHBOARD', CAST (NUGDG AS VARCHAR (10)) || ' - ' || TITULO
FROM TSIGDG
WHERE UPPER (CONFIG) LIKE UPPER ('%' || :BUSCA || '%')
UNION ALL
SELECT DISTINCT 'CAMPO', CAST (NUCAMPO AS VARCHAR (10)) || ' - ' || DESCRCAMPO
FROM TDDCAM
WHERE UPPER (EXPRESSAO) LIKE UPPER ('%' || :BUSCA || '%')
UNION ALL
SELECT DISTINCT 'AÇÃO', CAST (IDBTNACAO AS VARCHAR (10)) || ' - ' || DESCRICAO
FROM TSIBTA
WHERE UPPER (CONFIG) LIKE UPPER ('%' || :BUSCA || '%')
ORDER BY 2
