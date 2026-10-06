# Orphan Hunter

Script Python (boto3) **somente leitura** que varre uma conta AWS e gera um ranking, em US$ por mês, de recursos prováveis órfãos (que você paga e provavelmente não usa).

> Status: especificação. O código ainda será construído a partir de [orphan-hunter-prompt.md](orphan-hunter-prompt.md).

## Como funciona

1. Lista as regiões habilitadas (`ec2:DescribeRegions`), ou só as de `--regions`.
2. Roda 4 detectores em cada região:

| Detector | Regra de suspeita |
|---|---|
| Volume EBS solto | `State == "available"` |
| Elastic IP sem uso | sem `AssociationId` |
| Snapshot órfão | volume de origem não existe mais e nenhuma AMI usa o snapshot |
| Load balancer sem alvos | ALB/NLB sem targets, ou ~0 requests/bytes em 14 dias |

3. Calcula o custo mensal de cada item (quantidade × preço unitário da região). Preço não validado aparece como `?`.
4. Ordena por custo decrescente e mostra no terminal e em `orphans.md`: tipo, ID, região, custo/mês, idade, motivo (com evidência) e confiança (alta/média/baixa).

## Uso previsto

```bash
python orphan_hunter.py --regions sa-east-1,us-east-1 --usd-brl 5.50
```

## Princípios

- Só chamadas `Describe*`, `List*`, `Get*`. Nunca altera nem apaga nada: o script recomenda, quem age é você.
- Erro ou `AccessDenied` em uma região/detector vira aviso no fim do relatório; a execução continua.
- Custo de snapshot é estimativa superior (snapshots são incrementais).
- Apenas `boto3`, arquivo único, sem banco nem servidor.
