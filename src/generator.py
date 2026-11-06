# -*- coding: utf-8 -*-
"""生成层：按 Config 逐月计算工资 / 社保 / 公积金 / 银行流水 / 回单。

输入：src.config.Config
输出：DataSet（纯数据，供校验层与渲染层消费）
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from .config import Config, D_, r2, r1

D0 = Decimal("0")


@dataclass
class DataSet:
    payroll_rows: List[dict] = field(default_factory=list)     # 工资表行
    salary_by_period: Dict[Tuple[int, int], List[dict]] = field(default_factory=dict)
    social_rows: List[dict] = field(default_factory=list)      # 社保明细行（含补缴）
    hf_rows: List[dict] = field(default_factory=list)          # 公积金明细行
    flow: List[dict] = field(default_factory=list)             # 银行流水
    receipts: List[dict] = field(default_factory=list)         # 银行回单
    diff_map: Dict[Tuple[int, int], dict] = field(default_factory=dict)
    # 补差归集表：费款月 -> 险种个人部分差额（预缴月为正、settle 月为负）
    diff_total: Decimal = D0                                   # 补缴流水合计
    diff_base: Decimal = D0                                    # 补差基数（新下限-旧下限）


def tax_rate(cfg: Config, cum_taxable: Decimal):
    """按累计应纳税所得额返回 (税率, 速算扣除数)。"""
    for upper, rate, quick in cfg.tax_table:
        if upper is None or cum_taxable <= upper:
            return rate, quick
    return cfg.tax_table[-1][1], cfg.tax_table[-1][2]


def period_sort(p):
    return p[0] * 12 + p[1]


def prev_period(p):
    y, m = p
    return (y - 1, 12) if m == 1 else (y, m - 1)


def next_period(p):
    y, m = p
    return (y + 1, 1) if m == 12 else (y, m + 1)


def period_cn(p):
    return f"{p[0]}年{p[1]:02d}月"


def emp_on_payroll(e, period: Tuple[int, int]) -> bool:
    """员工在费款月是否在册（离职当月仍计薪/缴费，次月起停）。"""
    p = f"{period[0]:04d}-{period[1]:02d}"
    if e.hire[:7] > p:
        return False
    if e.leave and e.leave[:7] < p:
        return False
    return True


def _insurance_kinds(cfg: Config):
    """险种清单：(名称, 单位比例, 个人比例, 工资行键)。"""
    return [
        ("基本养老保险", cfg.rate_pension_corp, cfg.rate_pension_ind, "yl"),
        ("基本医疗保险", cfg.rate_medical_corp, cfg.rate_medical_ind, "yb"),
        ("生育保险（并入医疗合并征缴）", cfg.rate_maternity_corp, D0, None),
        ("失业保险", cfg.rate_unemployment_corp, cfg.rate_unemployment_ind, "sy"),
        ("工伤保险", cfg.rate_injury_corp, D0, None),
    ]


def _affected_employees(cfg: Config):
    """过渡期受影响员工：月薪低于新年度下限（按下限封顶者）。"""
    if cfg.transition is None:
        return []
    return [e for e in cfg.employees if e.salary < cfg.social_base_lower]


def _diff_contrib(cfg: Config, base_diff: Decimal) -> dict:
    """基数补差的个人部分（按险种）。"""
    return {
        "yl": r2(base_diff * cfg.rate_pension_ind),
        "yb": r2(base_diff * cfg.rate_medical_ind),
        "sy": r2(base_diff * cfg.rate_unemployment_ind),
    }


def compute(cfg: Config) -> DataSet:
    ds = DataSet()
    periods = cfg.periods()

    # ============ 一、工资表（含个税累计预扣） ============
    for period in periods:
        rows_this_period = []
        for e in cfg.employees:
            if not emp_on_payroll(e, period):
                continue
            # 基数：低于下限按下限封顶，高于上限按上限封顶；
            # 过渡期预缴月按旧下限口径
            base = max(e.salary, cfg.social_base_lower)
            sbase = min(base, cfg.social_base_upper)
            if (cfg.transition is not None
                    and period in cfg.transition.prepay_months
                    and e.salary < cfg.social_base_lower):
                sbase = min(max(e.salary, cfg.transition.old_lower),
                            cfg.social_base_upper)

            yl = r2(sbase * cfg.rate_pension_ind)
            yb = r2(sbase * cfg.rate_medical_ind) + cfg.djb_individual
            sy = r2(sbase * cfg.rate_unemployment_ind)
            hf_ind = r1(min(max(e.salary, cfg.hf_base_lower), cfg.hf_base_upper)
                        * cfg.hf_rate)
            insurance_sub = yl + yb + sy
            ded5 = insurance_sub + hf_ind

            # 个税：按工资所属月累计预扣
            gross = e.salary
            prev = [r for r in ds.payroll_rows if r["no"] == e.no]
            cum_gross = sum((r["gross"] for r in prev), D0) + gross
            cum_ded5 = (sum((r["insurance_sub"] for r in prev), D0)
                        + sum((r["hf_ind"] for r in prev), D0) + ded5)
            cum_deduct = sum((r["special_deduct"] for r in prev), D0) + e.deduct
            months_on = len(prev) + 1
            cum_taxable = (cum_gross - cfg.tax_threshold * months_on
                           - cum_ded5 - cum_deduct)
            cum_taxable_q = max(cum_taxable, D0).quantize(Decimal("0.01"))
            rate, quick = tax_rate(cfg, cum_taxable_q)
            cum_tax = max(r2(cum_taxable_q * rate - quick), D0)
            prev_cum_tax = sum((r["tax"] for r in prev), D0)
            tax = cum_tax - prev_cum_tax
            net = gross - ded5 - tax

            remark = ""
            if e.leave and e.leave[:7] == f"{period[0]:04d}-{period[1]:02d}":
                remark = f"{e.leave} 离职，离职当月工资照发；当月社保仍缴、次月停"
            if e.hire[:7] == f"{period[0]:04d}-{period[1]:02d}":
                remark = f"{e.hire} 入职，当月全月计薪（简化假设）；当月参保、次月缴费"

            ds.payroll_rows.append({
                "period": period, "no": e.no, "gross": gross,
                "yl": yl, "yb": yb, "sy": sy, "hf_ind": hf_ind,
                "insurance_sub": insurance_sub, "ded5": ded5,
                "hf_base": min(max(e.salary, cfg.hf_base_lower), cfg.hf_base_upper),
                "social_base": sbase,
                "cum_taxable": cum_taxable_q, "tax": tax, "net": net,
                "special_deduct": e.deduct, "remark": remark,
            })
            rows_this_period.append(ds.payroll_rows[-1])
        ds.salary_by_period[period] = rows_this_period

    # ============ 二、过渡期基数补差（补缴场景） ============
    affected = _affected_employees(cfg)
    if cfg.transition is not None and affected:
        tr = cfg.transition
        diff_base = cfg.social_base_lower - tr.old_lower
        ds.diff_base = diff_base
        d_per = _diff_contrib(cfg, diff_base)   # 单月补差（每预缴月相同）

        # settle 月工资行叠加补差个人部分（预缴月数倍），并重算该员工后续累计个税
        n_prepay = len(tr.prepay_months)
        for e in affected:
            row = next(r for r in ds.payroll_rows
                       if r["no"] == e.no and r["period"] == tr.settle_month)
            row["yl"] += d_per["yl"] * n_prepay
            row["yb"] += d_per["yb"] * n_prepay
            row["sy"] += d_per["sy"] * n_prepay
            add = (d_per["yl"] + d_per["yb"] + d_per["sy"]) * n_prepay
            row["insurance_sub"] += add
            row["ded5"] = row["insurance_sub"] + row["hf_ind"]
            rows_e = [r for r in ds.payroll_rows if r["no"] == e.no]
            cum_tax_prev = D0
            cum_g = cum_d5 = cum_sd = D0
            n = 0
            for r in rows_e:
                n += 1
                cum_g += r["gross"]
                cum_d5 += r["ded5"]
                cum_sd += r["special_deduct"]
                cum_t = max(cum_g - cfg.tax_threshold * n - cum_d5 - cum_sd,
                            D0).quantize(Decimal("0.01"))
                rate, quick = tax_rate(cfg, cum_t)
                cum_tax = max(r2(cum_t * rate - quick), D0)
                r["cum_taxable"] = cum_t
                r["tax"] = cum_tax - cum_tax_prev
                r["net"] = r["gross"] - r["ded5"] - r["tax"]
                cum_tax_prev = cum_tax

        # 勾稽归集表：预缴月为正、settle 月为负（补差随 settle 月工资代扣）
        for m in tr.prepay_months:
            ds.diff_map[m] = dict(d_per)
        ds.diff_map[tr.settle_month] = {
            k: -(d_per[k] * len(tr.prepay_months)) for k in ("yl", "yb", "sy")}

        ds.diff_total = ((d_per["yl"] + d_per["yb"] + d_per["sy"])
                         * n_prepay
                         + (r2(diff_base * cfg.rate_pension_corp)
                            + r2(diff_base * cfg.rate_medical_corp)
                            + r2(diff_base * cfg.rate_maternity_corp)
                            + r2(diff_base * cfg.rate_unemployment_corp)
                            + r2(diff_base * cfg.rate_injury_corp)) * n_prepay)

    # ============ 三、社保 / 公积金缴纳明细 ============
    for period in periods:
        rows = ds.salary_by_period[period]
        bases = [r["social_base"] for r in rows]
        hf_bases = [r["hf_base"] for r in rows]
        n_emp = len(rows)

        hf_u = sum((r1(b * cfg.hf_rate) for b in hf_bases), D0)
        ds.hf_rows.append({
            "period": period, "n": n_emp, "base": sum(hf_bases, D0),
            "corp": hf_u, "ind": hf_u, "sub": hf_u * 2,
            "kind": "住房公积金",
        })
        for kind, rc, ri, key in _insurance_kinds(cfg):
            corp = sum((r2(b * rc) for b in bases), D0)
            ind = sum((r2(b * ri) for b in bases), D0)
            if key == "yb":
                ind += cfg.djb_individual * n_emp
            ds.social_rows.append({
                "period": period, "kind": kind, "n": n_emp,
                "base": sum(bases, D0), "rc": rc, "corp": corp,
                "ri": ri, "ind": ind, "sub": corp + ind, "is_diff": False,
            })
        # 补缴行（仅过渡期受影响员工）
        if cfg.transition is not None and affected \
                and period in cfg.transition.prepay_months:
            diff_base = ds.diff_base
            d_per = _diff_contrib(cfg, diff_base)
            for kind, rc, ri, _key in _insurance_kinds(cfg):
                if kind.startswith("基本养老保险"):
                    corp, ind = r2(diff_base * rc), d_per["yl"]
                elif kind.startswith("基本医疗保险"):
                    corp, ind = r2(diff_base * rc), d_per["yb"]
                elif kind.startswith("失业"):
                    corp, ind = r2(diff_base * rc), d_per["sy"]
                else:
                    corp, ind = r2(diff_base * rc), D0
                ds.social_rows.append({
                    "period": period, "kind": kind, "n": 1,
                    "base": diff_base, "rc": rc, "corp": corp,
                    "ri": ri, "ind": ind, "sub": corp + ind, "is_diff": True,
                })

    ds.social_rows.sort(key=lambda r: (period_sort(r["period"]),
                                       1 if r["is_diff"] else 0))
    ds.hf_rows.sort(key=lambda r: period_sort(r["period"]))

    # ============ 四、银行流水与回单 ============
    seq = {"no": 0}

    def next_seq(prefix, d):
        seq["no"] += 1
        return f"{prefix}{d.strftime('%Y%m%d')}{seq['no']:04d}"

    # 1) 工资代发：所属月 M 的工资于 M+1 月 pay_day 日发放
    for row in ds.payroll_rows:
        y, m = next_period(row["period"])
        d = date(y, m, cfg.pay_day)
        emp = next(e for e in cfg.employees if e.no == row["no"])
        ds.flow.append({
            "date": d, "dir": "支出", "amount": row["net"],
            "party": f"{row['no']}（{emp.card}）",
            "summary": f"代发{row['period'][0]}年{row['period'][1]}月工资",
            "category": "工资代发",
        })
        ds.receipts.append({
            "no": next_seq("HD", d), "date": d, "payer": cfg.company,
            "payee": row["no"], "amount": row["net"],
            "purpose": f"代发{row['period'][0]}年{row['period'][1]}月工资",
        })

    # 2) 社保费：费款所属月 M 于 M+1 月 social_day 日由税务划扣
    for period in periods:
        rows = [r for r in ds.social_rows
                if r["period"] == period and not r["is_diff"]]
        total = sum((r["sub"] for r in rows), D0)
        y, m = next_period(period)
        d = date(y, m, cfg.social_day)
        ds.flow.append({
            "date": d, "dir": "支出", "amount": total,
            "party": f"{cfg.tax_authority}（社保费）",
            "summary": f"缴纳社会保险费（费款所属期{period[0]}年{period[1]}月）",
            "category": "社保缴费",
        })
        ds.receipts.append({
            "no": next_seq("HD", d), "date": d, "payer": cfg.company,
            "payee": cfg.tax_authority, "amount": total,
            "purpose": f"缴纳社会保险费（费款所属期{period[0]}年{period[1]}月）",
        })

    # 3) 补缴流水：settle 月内 20 日补收
    if cfg.transition is not None and affected:
        y, m = cfg.transition.settle_month
        d = date(y, m, 20)
        ds.flow.append({
            "date": d, "dir": "支出", "amount": ds.diff_total,
            "party": f"{cfg.tax_authority}（社保费）",
            "summary": ("补缴社会保险费（年度缴费基数上下限调整，费款所属期"
                        + "、".join(f"{p[0]}年{p[1]}月"
                                    for p in cfg.transition.prepay_months) + "）"),
            "category": "社保补缴",
        })
        ds.receipts.append({
            "no": next_seq("HD", d), "date": d, "payer": cfg.company,
            "payee": cfg.tax_authority, "amount": ds.diff_total,
            "purpose": ("补缴社会保险费（年度基数上下限调整，费款所属期"
                        + "、".join(f"{p[0]}年{p[1]}月"
                                    for p in cfg.transition.prepay_months) + "）"),
        })

    # 4) 公积金：当月 hf_day 日汇缴当月费款
    for period in periods:
        hf = next(r for r in ds.hf_rows if r["period"] == period)
        y, m = period
        d = date(y, m, cfg.hf_day)
        ds.flow.append({
            "date": d, "dir": "支出", "amount": hf["sub"],
            "party": cfg.hf_center,
            "summary": f"汇缴{y}年{m}月住房公积金",
            "category": "公积金汇缴",
        })
        ds.receipts.append({
            "no": next_seq("HD", d), "date": d, "payer": cfg.company,
            "payee": cfg.hf_center, "amount": hf["sub"],
            "purpose": f"汇缴{y}年{m}月住房公积金",
        })

    ds.flow.sort(key=lambda f: f["date"])
    ds.receipts.sort(key=lambda r: (r["date"], r["no"]))
    return ds
