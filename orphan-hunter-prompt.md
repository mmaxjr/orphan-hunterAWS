# Prompt: construir o Orphan Hunter

Cole o texto abaixo (a partir de "## Papel") em uma sessão do Claude Code aberta na pasta do projeto.

---

## Papel

Somos sócios construindo o **Orphan Hunter**: um script Python (boto3) **somente leitura** que varre uma conta AWS e entrega um ranking, em US$ por mês, de recursos prováveis órfãos. Quero seu julgamento técnico honesto. Se algo no pedido for supérfluo ou errado, diga e proponha o mais simples.

## Regras inegociáveis

1. **Somente leitura. Sem exceções.** Use apenas chamadas `Describe*`, `List*`, `Get*`. Nunca `Delete*`, `Modify*`, `Create*`, `Release*`, `Terminate*`, `Stop*`, `Put*`, nem tag. O script **recomenda**, quem age sou eu.
2. **Não invente preços, nomes de API ou campos.** Se não tiver certeza, marque `(a validar)` no código e no relatório. O único preço já validado é o do IPv4 público: US$ 0,005/hora (≈ US$ 3,60/mês).
3. **Não adicione o que não pedi:** sem banco de dados, sem servidor, sem framework de CLI além de `argparse`, sem classes onde uma função resolve, sem dependência além de `boto3`.
4. **Antes de escrever código**, anuncie em 5 linhas o plano (arquivos, funções, como vai testar) e espere meu "ok".

## Escopo do MVP (4 detectores, nada além)

| Detector | Regra | API de leitura |
|---|---|---|
| Volume EBS solto | `State == "available"` | `ec2:DescribeVolumes` |
| Elastic IP sem uso | sem `AssociationId` | `ec2:DescribeAddresses` |
| Snapshot órfão | volume de origem não existe mais **e** não é usado por nenhuma AMI | `ec2:DescribeSnapshots` (OwnerIds=self), `DescribeVolumes`, `DescribeImages` (Owners=self) |
| Load balancer sem alvos | ALB/NLB sem nenhum target registrado, ou `RequestCount`/`ProcessedBytes` ≈ 0 por 14 dias | `elasticloadbalancing:Describe*`, `cloudwatch:GetMetricData` |

Fora do escopo agora: NAT Gateway, RDS, relatório HTML, agendamento, notificações, qualquer ação de limpeza.

## Comportamento

- **Regiões:** por padrão, todas as habilitadas (`ec2:DescribeRegions`). Flag `--regions sa-east-1,us-east-1` para restringir.
- **Paginação:** use paginators do boto3 em toda chamada de lista.
- **Erros:** `AccessDenied` ou erro de uma região/detector não derruba a execução. Registre um aviso, continue, e liste os avisos no fim do relatório.
- **Custo mensal** = quantidade × preço unitário da região (volume: GB × preço/GB-mês pelo tipo; snapshot: GB × preço/GB-mês; IP: 3,60; LB: horas do mês × preço/hora).
- **Preços:** dicionário `PRICES` no topo do arquivo, por região e tipo. Preencha **apenas** valores que você validar na Pricing API (`pricing:GetProducts`) ou na documentação. Preço ausente → custo `?`, ordenado por último, com a nota "preço não validado". Não chute.
- **Snapshots:** são incrementais, então o custo é uma **estimativa superior** (usa o tamanho do volume). Marque como tal.
- **Ranking:** ordene por custo mensal decrescente. Cada linha: tipo, ID, região, custo/mês, idade em dias, motivo da suspeita, **confiança** (alta/média/baixa).
- **Saída:** tabela no terminal e arquivo `orphans.md` (Markdown). Total no topo. `--usd-brl 5.50` converte para R$ (a taxa é argumento meu, sem consultar API de câmbio).
- **Falso positivo:** sempre mostre a evidência (ex.: "State=available há 41 dias", "0 requests em 14 dias"). Janela mínima de métrica: 14 dias.

## Entregáveis

1. `orphan_hunter.py`: arquivo único, funções pequenas (um detector por função, uma função de ranking, uma de relatório).
2. `iam-policy.json`: política mínima, só as ações de leitura realmente usadas.
3. **Uma** checagem executável, sem framework de teste: um `demo()` ou `if __name__ == "__main__"` com `assert` sobre a função pura de cálculo/classificação, usando dados fictícios. Não crie mocks da AWS inteira.
4. `README.md` curto: como rodar, a política IAM, e os limites conhecidos.

## Critérios de aceite (verifique antes de dizer "pronto")

- [ ] Nenhuma chamada de escrita no código (rode um `grep` por `delete|terminate|modify|create|release|put_|stop_|tag` e me mostre o resultado).
- [ ] A política IAM contém exatamente as ações usadas, nem mais nem menos.
- [ ] A checagem com `assert` passa e você mostra a saída.
- [ ] Todo preço sem fonte aparece como `(a validar)` ou `?`.
- [ ] Rodou contra minha conta (ou, se não tiver credenciais, diga claramente que **não** rodou e por quê).

## Formato da sua resposta final

Máximo 10 linhas: o que foi feito, o que foi pulado de propósito e quando vale adicionar, o que ficou `(a validar)`.
