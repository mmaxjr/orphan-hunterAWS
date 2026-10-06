"""Orphan Hunter: varredura SOMENTE LEITURA de recursos AWS provavelmente órfãos."""
import argparse
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

HOURS_MONTH = 730
EIP_MONTH = 3.60  # IPv4 público: US$ 0,005/h (validado)
WINDOW_DAYS = 14

# Preços US$. Só entra o que foi validado; ausente => custo "?" (preço não validado).
# Chaves: ebs_gb[(região, tipo_volume)], snapshot_gb[região], lb_hour[(região, "application"|"network")]
PRICES = {
    "ebs_gb": {},       # (a validar) Pricing API: pricing:GetProducts
    "snapshot_gb": {},  # (a validar)
    "lb_hour": {},      # (a validar)
}


def monthly_cost(kind, region, qty=1, sub=None):
    """Função pura. Retorna US$/mês ou None se o preço não foi validado."""
    if kind == "eip":
        return EIP_MONTH
    if kind == "ebs":
        p = PRICES["ebs_gb"].get((region, sub))
        return None if p is None else qty * p
    if kind == "snapshot":
        p = PRICES["snapshot_gb"].get(region)
        return None if p is None else qty * p
    if kind == "lb":
        p = PRICES["lb_hour"].get((region, sub))
        return None if p is None else HOURS_MONTH * p
    raise ValueError(kind)


def age_days(dt):
    return (datetime.now(timezone.utc) - dt).days if dt else None


def finding(kind, rid, region, cost, age, reason, confidence, note=""):
    return dict(kind=kind, id=rid, region=region, cost=cost, age=age,
                reason=reason, confidence=confidence, note=note)


def paginate(client, op, key, **kw):
    for page in client.get_paginator(op).paginate(**kw):
        yield from page[key]


def detect_ebs(ec2, region):
    out = []
    for v in paginate(ec2, "describe_volumes", "Volumes",
                      Filters=[{"Name": "status", "Values": ["available"]}]):
        age = age_days(v["CreateTime"])
        out.append(finding("EBS", v["VolumeId"], region,
                           monthly_cost("ebs", region, v["Size"], v["VolumeType"]), age,
                           f"State=available, {v['Size']} GB {v['VolumeType']}, volume com {age} dias",
                           "alta"))
    return out


def detect_eip(ec2, region):
    return [finding("EIP", a.get("AllocationId", a["PublicIp"]), region,
                    monthly_cost("eip", region), None,
                    f"{a['PublicIp']} sem AssociationId", "alta")
            for a in ec2.describe_addresses()["Addresses"] if "AssociationId" not in a]


def detect_snapshots(ec2, region):
    vols = {v["VolumeId"] for v in paginate(ec2, "describe_volumes", "Volumes")}
    in_ami = {b["Ebs"]["SnapshotId"]
              for i in paginate(ec2, "describe_images", "Images", Owners=["self"])
              for b in i.get("BlockDeviceMappings", []) if "Ebs" in b and "SnapshotId" in b["Ebs"]}
    out = []
    for s in paginate(ec2, "describe_snapshots", "Snapshots", OwnerIds=["self"]):
        if s["VolumeId"] in vols or s["SnapshotId"] in in_ami or s["VolumeId"] == "vol-ffffffff":
            continue
        age = age_days(s["StartTime"])
        out.append(finding("Snapshot", s["SnapshotId"], region,
                           monthly_cost("snapshot", region, s["VolumeSize"]), age,
                           f"volume {s['VolumeId']} não existe e nenhuma AMI usa; snapshot com {age} dias",
                           "média", "estimativa superior (snapshots são incrementais)"))
    return out


def lb_traffic(cw, lb, start, end):
    ns, metric = (("AWS/ApplicationELB", "RequestCount") if lb["Type"] == "application"
                  else ("AWS/NetworkELB", "ProcessedBytes"))
    dim = lb["LoadBalancerArn"].split("loadbalancer/")[1]
    q = [{"Id": "m", "MetricStat": {"Metric": {"Namespace": ns, "MetricName": metric,
          "Dimensions": [{"Name": "LoadBalancer", "Value": dim}]},
          "Period": 86400, "Stat": "Sum"}}]
    res = cw.get_metric_data(MetricDataQueries=q, StartTime=start, EndTime=end)
    return sum(res["MetricDataResults"][0]["Values"]), metric


def detect_lbs(elb, cw, region):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=WINDOW_DAYS)
    out = []
    for lb in paginate(elb, "describe_load_balancers", "LoadBalancers"):
        if lb["Type"] not in ("application", "network"):
            continue
        cost = monthly_cost("lb", region, sub=lb["Type"])
        age = age_days(lb["CreatedTime"])
        tgs = list(paginate(elb, "describe_target_groups", "TargetGroups",
                            LoadBalancerArn=lb["LoadBalancerArn"]))
        n = sum(len(elb.describe_target_health(TargetGroupArn=t["TargetGroupArn"])
                    ["TargetHealthDescriptions"]) for t in tgs)
        if n == 0:
            out.append(finding("LB", lb["LoadBalancerName"], region, cost, age,
                               f"{lb['Type']} sem nenhum target registrado", "alta"))
            continue
        total, metric = lb_traffic(cw, lb, start, end)
        if total == 0:
            out.append(finding("LB", lb["LoadBalancerName"], region, cost, age,
                               f"{n} targets, mas {metric}=0 em {WINDOW_DAYS} dias", "média"))
    return out


def rank(findings):
    """Custo decrescente; custo desconhecido (None) por último."""
    return sorted(findings, key=lambda f: (f["cost"] is None, -(f["cost"] or 0)))


def report(findings, warnings, usd_brl=None):
    known = sum(f["cost"] for f in findings if f["cost"] is not None)
    unk = sum(f["cost"] is None for f in findings)
    total = f"**Total conhecido: US$ {known:.2f}/mês**"
    if usd_brl:
        total += f" (R$ {known * usd_brl:.2f} a {usd_brl})"
    if unk:
        total += f" + {unk} item(ns) com preço não validado (`?`)"
    lines = ["# Orphan Hunter", "", total, "",
             "| Tipo | ID | Região | Custo/mês | Idade (dias) | Motivo | Confiança |",
             "|---|---|---|---|---|---|---|"]
    for f in findings:
        c = "? (preço não validado)" if f["cost"] is None else f"US$ {f['cost']:.2f}"
        note = f" ({f['note']})" if f["note"] else ""
        age = "-" if f["age"] is None else f["age"]
        lines.append(f"| {f['kind']} | {f['id']} | {f['region']} | {c} | {age} | "
                     f"{f['reason']}{note} | {f['confidence']} |")
    if warnings:
        lines += ["", "## Avisos", *[f"- {w}" for w in warnings]]
    return "\n".join(lines) + "\n"


def scan(regions, warnings):
    found = []
    for r in regions:
        ec2 = boto3.client("ec2", region_name=r)
        elb = boto3.client("elbv2", region_name=r)
        cw = boto3.client("cloudwatch", region_name=r)
        for name, fn in (("EBS", lambda: detect_ebs(ec2, r)), ("EIP", lambda: detect_eip(ec2, r)),
                         ("Snapshot", lambda: detect_snapshots(ec2, r)),
                         ("LB", lambda: detect_lbs(elb, cw, r))):
            try:
                found += fn()
            except (ClientError, BotoCoreError) as e:
                warnings.append(f"{r}/{name}: {e}")
    return found


def main():
    ap = argparse.ArgumentParser(description="Varredura somente leitura de recursos AWS órfãos")
    ap.add_argument("--regions", help="ex.: sa-east-1,us-east-1 (padrão: todas habilitadas)")
    ap.add_argument("--usd-brl", type=float, help="taxa de câmbio informada por você")
    ap.add_argument("--demo", action="store_true", help="roda a checagem com dados fictícios")
    a = ap.parse_args()
    if a.demo:
        return demo()
    warnings = []
    regions = a.regions.split(",") if a.regions else [
        r["RegionName"] for r in boto3.client("ec2", region_name="us-east-1").describe_regions()["Regions"]]
    md = report(rank(scan(regions, warnings)), warnings, a.usd_brl)
    print(md)
    with open("orphans.md", "w", encoding="utf-8") as f:
        f.write(md)


def demo():
    assert monthly_cost("eip", "sa-east-1") == 3.60
    assert monthly_cost("ebs", "sa-east-1", 100, "gp3") is None  # preço não validado
    PRICES["ebs_gb"][("x", "gp3")] = 0.10  # valor fictício, só para o teste
    assert abs(monthly_cost("ebs", "x", 100, "gp3") - 10.0) < 1e-9
    fs = [finding("A", "1", "x", None, 1, "r", "alta"), finding("B", "2", "x", 3.6, 1, "r", "alta"),
          finding("C", "3", "x", 10.0, 1, "r", "alta")]
    assert [f["id"] for f in rank(fs)] == ["3", "2", "1"]
    out = report(rank(fs), ["aviso"], 5.0)
    assert "US$ 13.60" in out and "R$ 68.00" in out and "1 item(ns)" in out and "- aviso" in out
    print("demo OK")


if __name__ == "__main__":
    main()
