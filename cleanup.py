"""Limpeza OPCIONAL dos achados de orphans.json. DESTRUTIVO e irreversível.

Separado de orphan_hunter.py de propósito: o scanner continua somente leitura.
Padrão é dry-run. Para apagar: --execute, e você digita o ID de cada recurso para confirmar.
Só itens de confiança "alta" (use --include-medium para os de média). RDS nunca é apagado aqui.
"""
import argparse
import json

import boto3

# tipo -> (serviço boto3, função que apaga o recurso a partir do cliente e do ref)
ACTIONS = {
    "EBS": ("ec2", lambda c, ref: c.delete_volume(VolumeId=ref)),
    "EIP": ("ec2", lambda c, ref: c.release_address(AllocationId=ref)),
    "Snapshot": ("ec2", lambda c, ref: c.delete_snapshot(SnapshotId=ref)),
    "LB": ("elbv2", lambda c, ref: c.delete_load_balancer(LoadBalancerArn=ref)),
    "NAT": ("ec2", lambda c, ref: c.delete_nat_gateway(NatGatewayId=ref)),
}


def select(findings, include_medium=False):
    ok = {"alta", "média"} if include_medium else {"alta"}
    return [f for f in findings if f["kind"] in ACTIONS and f["confidence"] in ok]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", default="orphans.json")
    ap.add_argument("--execute", action="store_true", help="apaga de verdade (padrão: dry-run)")
    ap.add_argument("--include-medium", action="store_true")
    a = ap.parse_args()
    with open(a.file, encoding="utf-8") as f:
        items = select(json.load(f), a.include_medium)
    for f in items:
        label = f"{f['kind']} {f['id']} ({f['region']}): {f['reason']}"
        if not a.execute:
            print(f"[dry-run] apagaria {label}")
            continue
        if input(f"Apagar {label}\nDigite o ID '{f['id']}' para confirmar (Enter pula): ") != f["id"]:
            print("  pulado")
            continue
        service, action = ACTIONS[f["kind"]]
        try:
            action(boto3.client(service, region_name=f["region"]), f["ref"])
            print("  apagado")
        except Exception as e:  # noqa: BLE001 - segue para o próximo item
            print(f"  ERRO: {e}")


def demo():
    fs = [{"kind": "EBS", "confidence": "alta"}, {"kind": "Snapshot", "confidence": "média"},
          {"kind": "RDS", "confidence": "alta"}]
    assert [f["kind"] for f in select(fs)] == ["EBS"]
    assert [f["kind"] for f in select(fs, True)] == ["EBS", "Snapshot"]
    print("cleanup demo OK")


if __name__ == "__main__":
    import sys
    demo() if sys.argv[1:] == ["--demo"] else main()
