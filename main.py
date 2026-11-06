# -*- coding: utf-8 -*-
"""一键运行：生成中国口径勾稽自洽的会计/社保样例数据工作簿。

用法：
    python main.py                       # 输出到 ./output/样例数据.xlsx
    python main.py --out 路径.xlsx        # 指定输出文件
    python main.py --csv-dir 目录        # 同时输出中间 CSV（留痕）
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import beijing_2025_config, compute, Validator, render
from src.generator import period_cn


def dump_csv(csv_dir, name, header, rows_iter):
    p = os.path.join(csv_dir, name)
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows_iter:
            w.writerow(row)
    print(f"[CSV] {p}")


def main():
    ap = argparse.ArgumentParser(description="中国口径勾稽自洽样例数据生成器")
    ap.add_argument("--out", default=None, help="输出 xlsx 路径")
    ap.add_argument("--csv-dir", default=None, help="中间 CSV 输出目录（可选）")
    args = ap.parse_args()

    cfg = beijing_2025_config()   # 换城市/年度/人数：仿照此函数改 Config 即可
    ds = compute(cfg)

    checks = Validator(cfg, ds).run()   # 任何一项不平直接抛异常
    print(f"[OK] 工资表 {len(ds.payroll_rows)} 行；社保明细 {len(ds.social_rows)} 行"
          f"（含补缴行）；公积金明细 {len(ds.hf_rows)} 行；"
          f"流水 {len(ds.flow)} 笔；回单 {len(ds.receipts)} 条；"
          f"勾稽校验 {len(checks)} 项全部通过")

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "output", "样例数据.xlsx")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    n, ok = render(cfg, ds, checks, out)
    print(f"[OK] 已生成: {out}（勾稽 {n} 项，通过 {ok} 项）")

    if args.csv_dir:
        os.makedirs(args.csv_dir, exist_ok=True)
        dump_csv(args.csv_dir, "工资表.csv",
                 ["工资所属期", "员工编号", "应发工资", "养老个人", "医疗个人",
                  "失业个人", "公积金个人", "个人五险一金小计", "累计应纳税所得额",
                  "当月个税", "实发工资", "备注"],
                 ([period_cn(r["period"]), r["no"], r["gross"], r["yl"], r["yb"],
                   r["sy"], r["hf_ind"], r["ded5"], r["cum_taxable"], r["tax"],
                   r["net"], r["remark"]] for r in ds.payroll_rows))
        dump_csv(args.csv_dir, "社保公积金明细.csv",
                 ["费款所属期", "险种", "人数", "基数合计", "单位比例", "单位金额",
                  "个人比例", "个人金额", "合计", "补缴标记"],
                 ([period_cn(r["period"]), r["kind"], r["n"], r["base"],
                   r.get("rc", cfg.hf_rate),
                   r["corp"], r.get("ri", cfg.hf_rate), r["ind"], r["sub"],
                   "补缴" if r.get("is_diff") else ""]
                  for r in ds.social_rows + ds.hf_rows))
        dump_csv(args.csv_dir, "银行流水.csv",
                 ["交易日期", "方向", "金额", "对方户名", "摘要", "类别"],
                 ([f["date"].isoformat(), f["dir"], f["amount"], f["party"],
                   f["summary"], f["category"]] for f in ds.flow))
        dump_csv(args.csv_dir, "勾稽校验.csv",
                 ["校验期间", "校验项", "表A", "表B", "差异", "是否通过", "说明"],
                 ([c["month"], c["item"], c["a"], c["b"], c["diff"],
                   "通过" if c["ok"] else "不通过", c["note"]] for c in checks))

    print("\n===== 关键汇总 =====")
    from decimal import Decimal
    D0 = Decimal("0")
    print("工资表行数:", len(ds.payroll_rows))
    print("应发合计:", sum((r["gross"] for r in ds.payroll_rows), D0))
    print("实发合计:", sum((r["net"] for r in ds.payroll_rows), D0))
    print("个税合计:", sum((r["tax"] for r in ds.payroll_rows), D0))
    print("社保明细合计（含补缴）:", sum((r["sub"] for r in ds.social_rows), D0))
    print("公积金明细合计:", sum((r["sub"] for r in ds.hf_rows), D0))
    print("流水支出合计:", sum((f["amount"] for f in ds.flow), D0))


if __name__ == "__main__":
    main()
