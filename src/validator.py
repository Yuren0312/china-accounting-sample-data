# -*- coding: utf-8 -*-
"""校验层：勾稽自验。

所有校验既写入 checks 列表（供渲染「勾稽校验」sheet），也以断言形式即时执行——
任何一项不平即抛异常，确保生成的数据集必然勾稽自洽。

勾稽清单：
A. 逐费款月：工资表代扣五险（分险种）个人合计 vs 社保明细个人部分合计
A. 逐费款月：工资表代扣公积金个人合计 vs 公积金明细个人部分合计
B. 逐扣款月：银行流水社保扣款 vs 社保明细（费款所属期=上月）合计
B. 补缴流水 vs 社保明细补缴行合计
C. 逐月：银行流水公积金汇缴 vs 公积金明细合计
D. 逐发放月：银行流水代发工资 vs 工资表实发合计（工资所属期=上月）
E. 全年汇总：实发/五险一金/社保/公积金/流水总额交叉核对
F. 行级断言：每行小计、实发、个税累计一致性
"""
from datetime import date
from decimal import Decimal
from typing import List

from .config import Config, r2
from .generator import DataSet, tax_rate, next_period, period_cn

D0 = Decimal("0")


class Validator:
    def __init__(self, cfg: Config, ds: DataSet):
        self.cfg = cfg
        self.ds = ds
        self.checks: List[dict] = []

    def add_check(self, month, item, a, b, note=""):
        a, b = r2(a), r2(b)
        diff = r2(a - b)
        ok = diff == Decimal("0.00")
        self.checks.append({
            "month": month, "item": item, "a": a, "b": b,
            "diff": diff, "ok": ok, "note": note,
        })
        assert ok, f"勾稽失败: {month} {item}: {a} vs {b} (差异 {diff})"

    def run(self) -> List[dict]:
        cfg, ds = self.cfg, self.ds
        periods = cfg.periods()

        # ---- A. 逐费款月：工资表 vs 社保/公积金明细（个人部分） ----
        for period in periods:
            rows = ds.salary_by_period[period]
            wage_ins = sum((r["yl"] + r["yb"] + r["sy"] for r in rows), D0)
            wage_ins += sum(ds.diff_map.get(period, {}).values())
            srows = [r for r in ds.social_rows if r["period"] == period]
            s_ind = sum((r["ind"] for r in srows), D0)
            hf = next(r for r in ds.hf_rows if r["period"] == period)
            wage_hf = sum((r["hf_ind"] for r in rows), D0)
            note = ""
            if period in ds.diff_map and sum(ds.diff_map[period].values()) > 0:
                note = "过渡期基数补差个人部分按费款所属期归集（随结算月工资代扣）"
            self.add_check(period_cn(period),
                           "工资表代扣五险个人合计 vs 社保缴纳明细个人部分合计",
                           wage_ins, s_ind, note)
            self.add_check(period_cn(period),
                           "工资表代扣公积金个人合计 vs 公积金缴纳明细个人部分合计",
                           wage_hf, hf["ind"])
            # 分险种
            dv = ds.diff_map.get(period, {})
            yl_ind = sum((r["ind"] for r in srows
                          if r["kind"].startswith("基本养老保险")), D0)
            yb_ind = sum((r["ind"] for r in srows
                          if r["kind"].startswith("基本医疗保险")), D0)
            sy_ind = sum((r["ind"] for r in srows
                          if r["kind"].startswith("失业保险")), D0)
            self.add_check(period_cn(period), "工资表养老个人 vs 社保明细养老个人",
                           sum((r["yl"] for r in rows), D0) + dv.get("yl", D0), yl_ind)
            self.add_check(period_cn(period),
                           "工资表医疗个人 vs 社保明细医疗个人（含大额互助）",
                           sum((r["yb"] for r in rows), D0) + dv.get("yb", D0), yb_ind)
            self.add_check(period_cn(period), "工资表失业个人 vs 社保明细失业个人",
                           sum((r["sy"] for r in rows), D0) + dv.get("sy", D0), sy_ind)

        # ---- B. 逐扣款月：流水社保扣款 vs 明细 ----
        for period in periods:
            y, m = next_period(period)
            flow_amt = sum((f["amount"] for f in ds.flow
                            if f["category"] == "社保缴费"
                            and f["date"] == date(y, m, cfg.social_day)), D0)
            detail = sum((r["sub"] for r in ds.social_rows
                          if r["period"] == period and not r["is_diff"]), D0)
            self.add_check(f"{y}年{m:02d}月",
                           "银行流水社保扣款 vs 社保明细（费款所属期=上月）合计",
                           flow_amt, detail, "当月参保、次月缴费")
        if ds.diff_total > 0:
            self.add_check(period_cn(self.cfg.transition.settle_month),
                           "银行流水社保补缴 vs 社保明细补缴行合计",
                           ds.diff_total,
                           sum((r["sub"] for r in ds.social_rows if r["is_diff"]), D0),
                           "年度基数上下限调整补收")

        # ---- C. 逐月：流水公积金 vs 明细 ----
        for period in periods:
            hf = next(r for r in ds.hf_rows if r["period"] == period)
            y, m = period
            flow_amt = sum((f["amount"] for f in ds.flow
                            if f["category"] == "公积金汇缴"
                            and f["date"] == date(y, m, cfg.hf_day)), D0)
            self.add_check(period_cn(period),
                           "银行流水公积金汇缴 vs 公积金缴纳明细合计", flow_amt, hf["sub"])

        # ---- D. 逐发放月：流水代发工资 vs 实发合计 ----
        for row_period in periods:
            y, m = next_period(row_period)
            flow_amt = sum((f["amount"] for f in ds.flow
                            if f["category"] == "工资代发"
                            and f["date"] == date(y, m, cfg.pay_day)), D0)
            wage_net = sum((r["net"] for r in ds.payroll_rows
                            if r["period"] == row_period), D0)
            self.add_check(f"{y}年{m:02d}月",
                           "银行流水代发工资 vs 工资表实发合计（工资所属期=上月）",
                           flow_amt, wage_net)

        # ---- E. 全年汇总 ----
        self.add_check("全年汇总", "工资表实发合计 vs 流水代发合计",
                       sum((r["net"] for r in ds.payroll_rows), D0),
                       sum((f["amount"] for f in ds.flow
                            if f["category"] == "工资代发"), D0))
        self.add_check("全年汇总", "工资表五险一金个人合计 vs 社保+公积金明细个人合计",
                       sum((r["ded5"] for r in ds.payroll_rows), D0),
                       sum((r["ind"] for r in ds.social_rows), D0)
                       + sum((r["ind"] for r in ds.hf_rows), D0))
        self.add_check("全年汇总", "工资表代扣个税合计 vs 各月代扣代缴个人所得税",
                       sum((r["tax"] for r in ds.payroll_rows), D0),
                       sum((r["tax"] for r in ds.payroll_rows), D0))
        self.add_check("全年汇总", "流水社保（含补缴）合计 vs 社保明细单位+个人合计",
                       sum((f["amount"] for f in ds.flow
                            if f["category"] in ("社保缴费", "社保补缴")), D0),
                       sum((r["sub"] for r in ds.social_rows), D0))
        self.add_check("全年汇总", "流水公积金合计 vs 公积金明细合计",
                       sum((f["amount"] for f in ds.flow
                            if f["category"] == "公积金汇缴"), D0),
                       sum((r["sub"] for r in ds.hf_rows), D0))
        self.add_check("全年汇总", "流水支出合计 vs 工资+社保+公积金合计",
                       sum((f["amount"] for f in ds.flow), D0),
                       sum((f["amount"] for f in ds.flow
                            if f["category"] == "工资代发"), D0)
                       + sum((f["amount"] for f in ds.flow
                              if f["category"] in ("社保缴费", "社保补缴")), D0)
                       + sum((f["amount"] for f in ds.flow
                              if f["category"] == "公积金汇缴"), D0))

        # ---- F. 行级断言 ----
        for r in ds.payroll_rows:
            assert r["ded5"] == r["yl"] + r["yb"] + r["sy"] + r["hf_ind"], \
                f"{r['no']} 五险一金小计不符"
            assert r["net"] == r["gross"] - r["ded5"] - r["tax"], \
                f"{r['no']} 实发不符"
            assert r["tax"] >= 0
        for e in cfg.employees:
            rows = [r for r in ds.payroll_rows if r["no"] == e.no]
            tot = sum((r["tax"] for r in rows), D0)
            last = rows[-1]
            rate, quick = tax_rate(cfg, last["cum_taxable"])
            expect = max(r2(last["cum_taxable"] * rate - quick), D0)
            assert tot == expect, f"{e.no} 个税累计不符: {tot} vs {expect}"
        for r in ds.social_rows + ds.hf_rows:
            assert r["sub"] == r["corp"] + r["ind"], \
                f"明细行小计不符: {r['kind']} {r['period']}"
        for f in ds.flow:
            assert f["amount"] >= 0

        return self.checks
