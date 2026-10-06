# Orphan Hunter

Script Python (boto3) que varre uma conta AWS e gera um ranking, em US$ por mês, de recursos prováveis órfãos (que você paga e provavelmente não usa).

O scanner (`orphan_hunter.py`) é **somente leitura**. A limpeza é opcional e fica em outro arquivo (`cleanup.py`), com política IAM própria.

Especificação original: [orphan-hunter-prompt.md](orphan-hunter-prompt.md).

## Como funciona

1. Lista as regiões habilitadas (`ec2:DescribeRegions`), ou só as de `--regions`.
2. Roda 6 detectores em cada região:

| Detector | Regra de suspeita |
|---|---|
| Volume EBS solto | `State == "available"` |
| Elastic IP sem uso | sem `AssociationId` |
| Snapshot órfão | volume de origem não existe mais e nenhuma AMI usa o snapshot |
| Load balancer (ALB/NLB) | sem targets, ou ~0 requests/bytes em 14 dias |
| NAT Gateway | `BytesOutToDestination` = 0 em 14 dias |
| RDS | instância `available` com 0 conexões em 14 dias |

3. Calcula o custo mensal de cada item (quantidade × preço unitário da região). Preço não validado aparece como `?`.
4. Ordena por custo decrescente e grava `orphans.md`, `orphans.html` e `orphans.json`: tipo, ID, região, custo/mês, idade, motivo (com evidência) e confiança (alta/média/baixa).

## Uso

```bash
pip install boto3
python orphan_hunter.py --regions sa-east-1,us-east-1 --usd-brl 5.50
python orphan_hunter.py --webhook https://hooks.slack.com/...   # envia o resumo
python orphan_hunter.py --demo                                   # checagem com dados fictícios
```

Usa as credenciais AWS padrão do boto3. Política mínima de leitura: [iam-policy.json](iam-policy.json).

## Agendamento

[.github/workflows/scan.yml](.github/workflows/scan.yml) roda toda segunda-feira (e manualmente) e publica os relatórios como artefato. Só executa se existir a variável de repositório `AWS_ROLE_ARN` (role OIDC com `iam-policy.json`). O secret opcional `WEBHOOK_URL` ativa a notificação.

## Limpeza (opcional, destrutiva)

```bash
python cleanup.py                 # dry-run: só lista o que apagaria
python cleanup.py --execute       # apaga item a item, você digita o ID para confirmar
python cleanup.py --include-medium
```

- Lê `orphans.json`; por padrão só itens de confiança **alta**.
- Cobre EBS, EIP, snapshot, LB e NAT. **RDS nunca é apagado** por aqui.
- Exige a política [iam-cleanup-policy.json](iam-cleanup-policy.json), separada da de leitura.
- Apagar é irreversível. Revise o relatório antes.

## Limites conhecidos

- Só o preço do IPv4 está validado. Preços de EBS, snapshot, LB, NAT e RDS estão `(a validar)` em `PRICES`; até lá o custo aparece como `?`.
- Custo de snapshot é estimativa superior (snapshots são incrementais); custo de RDS e NAT não inclui storage/tráfego.
- Classic Load Balancer fora do escopo; só ALB/NLB.
- Idade do EBS é a do volume, não há quanto tempo está `available`.
- Não foi executado contra uma conta real ainda; o workflow do GitHub Actions também não foi testado.
