# Questionário de lentidão

Perguntas ao cliente antes da análise. Vêm do material oficial do Service Desk Sankhya.

Não são pré-requisito para rodar o coletor, mas mudam a leitura das evidências: o pacote de
log mostra **o que aconteceu no servidor**, o questionário mostra **o que o usuário sentiu**.
Um erro que aparece 5.000 vezes no log e não corresponde a nenhuma queixa é ruído; um que
aparece 12 vezes exatamente no horário reclamado é o achado principal.

## As perguntas

1. Quando começou a ocorrer a lentidão?
2. Existe um horário específico, ou ocorre a todo momento?
3. Em quais rotinas do sistema ocorre?
4. Foi feito algum tipo de atualização recente?
5. Acontece com todos os usuários?
6. Acontece em todas as máquinas?
7. Acontece em todos os navegadores?
8. Foram feitas mudanças na estrutura do banco de dados ou do servidor?
9. Existe integração com outro sistema, extensões ou objetos personalizados que participam
   do processo?
10. Acontece em bases de produção e de testes?
11. Há algum agendamento sendo executado (análise de giro, consolidação, e-mails…)?
12. Foi realizado algum ajuste de configuração ou parâmetro para esta rotina recentemente?

## Como cada resposta muda a análise

| Pergunta | Resposta que muda o rumo |
|---|---|
| 1 | Data de início delimita a janela do log. Sem ela, a análise cobre todo o pacote e dilui o sinal |
| 2 | Horário específico → olhar jobs, backup e integrações naquela faixa antes de qualquer outra coisa |
| 3 | Rotina específica → lentidão localizada; cruzar com as telas mais usadas no `.ald` |
| 4 | Atualização recente → comparar a data com o início dos erros no log |
| 5 e 6 | "Alguns usuários" ou "algumas máquinas" aponta para estação e rede, **não** para servidor |
| 7 | Só um navegador → problema de cliente, fora do alcance do pacote |
| 8 | Mudança de estrutura → estatísticas do banco desatualizadas, índice removido |
| 9 | Integração ou personalização no caminho → é onde o checklist manda olhar primeiro |
| 10 | Lento também em teste, com menos carga → indica código ou consulta, não capacidade |
| 11 | Agendamento ativo → cruzar com a distribuição de erro por hora |
| 12 | Parâmetro alterado → o mais barato de reverter e o mais esquecido |

Perguntas 5, 6 e 7 juntas separam problema de servidor de problema de estação — a
distinção que evita a análise inteira apontar para o lugar errado.

## Quando o usuário não tem as respostas

Seguir com a análise e registrar na seção de metodologia que o sintoma percebido não foi
informado. As conclusões passam a valer para o ambiente como um todo, não para a queixa
específica, e o documento tem de dizer isso — senão o cliente lê um diagnóstico geral como
resposta ao problema dele.
