# -*- coding: utf-8 -*-
"""渲染层：把 DataSet 渲染为单工作簿 7 个 sheet 的 .xlsx。

sheet 结构（表头用中国实际报表用语）：
1 员工花名册 / 2 工资表 / 3 社保公积金缴纳明细 / 4 银行流水
5 银行回单 / 6 勾稽校验 / 7 口径说明
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .config import Config, r2
from .generator import DataSet, period_cn

HDR_FILL = PatternFill("solid", fgColor="2F5496")
HDR_FONT = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="微软雅黑", size=10)
DIFF_FILL = PatternFill("solid", fgColor="FCE4D6")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
CENTER = Alignment(horizontal="center", vertical="center")
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
RIGHT = Alignment(horizontal="right", vertical="center")

MATERNITY_NOTE = "生育保险自2019年并入医疗保险，比例仍单列、费款合并征缴"


def _style_sheet(ws, widths, num_cols=(), n_head_rows=1):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=len(widths)):
        for c in row:
            c.border = BORDER
            if c.row <= n_head_rows:
                c.fill = HDR_FILL
                c.font = HDR_FONT
                c.alignment = CENTER
            else:
                c.font = BODY_FONT
                if c.column in num_cols:
                    c.number_format = "#,##0.00"
                    c.alignment = RIGHT
                else:
                    c.alignment = CENTER
    ws.freeze_panes = f"A{n_head_rows + 1}"


def _social_note(cfg: Config, r) -> str:
    if r["is_diff"]:
        return ("年度缴费基数上下限调整补收（"
                + "、".join(f"{p[0]}年{p[1]}月" for p in cfg.transition.prepay_months)
                + "费款，仅按下限封顶的员工）")
    if r["period"] in cfg.transition.prepay_months:
        months_txt = "、".join(f"{p[0]}年{p[1]}月"
                               for p in cfg.transition.prepay_months)
        return (f"{months_txt}费款按上年度下限{cfg.transition.old_lower}元预缴，"
                f"调整月统一补差")
    return ""


def render(cfg: Config, ds: DataSet, checks, out_path: str):
    wb = openpyxl.Workbook()

    # --- Sheet1 员工花名册 ---
    ws = wb.active
    ws.title = "员工花名册"
    ws.append(["员工编号", "姓名（脱敏）", "证件号码（脱敏）", "入职日期", "离职日期",
               "月薪（元）", "社保缴费基数（元）", "公积金缴费基数（元）",
               "公积金缴存比例", "银行卡号（虚构）", "专项附加扣除合计（元/月）", "备注"])
    for e in cfg.employees:
        base = max(e.salary, cfg.social_base_lower)
        sbase = min(base, cfg.social_base_upper)
        hf_base = min(max(e.salary, cfg.hf_base_lower), cfg.hf_base_upper)
        ws.append([e.no, e.name, e.id_no, e.hire, e.leave or "—",
                   float(e.salary), float(sbase), float(hf_base),
                   f"{float(cfg.hf_rate) * 100:.0f}%", e.card,
                   float(e.deduct), e.note])
    _style_sheet(ws, [10, 12, 14, 11, 11, 11, 14, 14, 12, 20, 14, 52],
                 num_cols=(6, 7, 8, 11))
    for i in range(2, ws.max_row + 1):
        for col in (6, 7, 8, 11):
            ws.cell(row=i, column=col).number_format = "#,##0"

    # --- Sheet2 工资表 ---
    ws = wb.create_sheet("工资表")
    ws.append(["工资所属期", "员工编号", "应发工资", "代扣代缴—养老保险（个人8%）",
               "代扣代缴—医疗保险（个人2%＋大额互助）", "代扣代缴—失业保险（个人0.5%）",
               "代扣代缴—住房公积金（个人12%）", "个人五险一金小计",
               "累计应纳税所得额", "代扣代缴个人所得税", "实发工资", "备注"])
    for r in ds.payroll_rows:
        ws.append([period_cn(r["period"]), r["no"], float(r["gross"]),
                   float(r["yl"]), float(r["yb"]), float(r["sy"]),
                   float(r["hf_ind"]), float(r["ded5"]),
                   float(r["cum_taxable"]), float(r["tax"]), float(r["net"]),
                   r["remark"]])
    _style_sheet(ws, [11, 9, 11, 15, 16, 15, 15, 12, 14, 13, 12, 40],
                 num_cols=(3, 4, 5, 6, 7, 8, 9, 10, 11))

    # --- Sheet3 社保公积金缴纳明细 ---
    ws = wb.create_sheet("社保公积金缴纳明细")
    ws.append(["费款所属期", "险种", "缴费人数", "缴费基数合计（元）",
               "单位比例", "单位部分（元）", "个人比例", "个人部分（元）",
               "合计（元）", "补缴标记", "备注"])
    for r in ds.social_rows:
        note = _social_note(cfg, r)
        if not note and r["kind"].startswith("基本医疗保险"):
            note = ("单位9.8%（基本医疗9%＋生育0.8%合并征缴）；"
                    "个人2%＋3元大额医疗互助")
        elif not note and r["kind"].startswith("生育"):
            note = MATERNITY_NOTE
        elif not note and r["kind"].startswith("工伤"):
            note = "二类行业基准费率0.4%；北京2025-01-01起停止阶段性降费，按全国基准执行"
        ws.append([period_cn(r["period"]), r["kind"], r["n"], float(r["base"]),
                   f'{float(r["rc"]) * 100:.1f}%', float(r["corp"]),
                   (f'{float(r["ri"]) * 100:.1f}%' if float(r["ri"]) > 0 else "—"),
                   float(r["ind"]), float(r["sub"]),
                   "补缴" if r["is_diff"] else "", note])
    for r in ds.hf_rows:
        ws.append([period_cn(r["period"]), r["kind"], r["n"], float(r["base"]),
                   "12%", float(r["corp"]), "12%", float(r["ind"]),
                   float(r["sub"]), "", "2025住房公积金年度缴存比例5%~12%，本案取12%"])
    _style_sheet(ws, [12, 24, 9, 16, 9, 13, 9, 13, 12, 9, 52],
                 num_cols=(4, 6, 8, 9))
    for i in range(2, ws.max_row + 1):
        if ws.cell(row=i, column=10).value == "补缴":
            for j in range(1, 12):
                ws.cell(row=i, column=j).fill = DIFF_FILL

    # --- Sheet4 银行流水 ---
    ws = wb.create_sheet("银行流水")
    ws.append(["序号", "交易日期", "收支方向", "金额（元）", "对方户名", "摘要", "类别"])
    for i, f in enumerate(ds.flow, 1):
        ws.append([i, f["date"].strftime("%Y-%m-%d"), f["dir"], float(f["amount"]),
                   f["party"], f["summary"], f["category"]])
    _style_sheet(ws, [6, 12, 9, 13, 34, 52, 11], num_cols=(4,))
    for i in range(2, ws.max_row + 1):
        ws.cell(row=i, column=2).number_format = "yyyy-mm-dd"
        ws.cell(row=i, column=4).number_format = "#,##0.00"

    # --- Sheet5 银行回单 ---
    ws = wb.create_sheet("银行回单")
    ws.append(["回单编号", "交易日期", "付款户名", "付款账号", "收款户名",
               "金额（元）", "用途"])
    payee_acc = {cfg.tax_authority: cfg.tax_account, cfg.hf_center: cfg.hf_account}
    for r in ds.receipts:
        if r["payee"] in payee_acc:
            acc = payee_acc[r["payee"]]
        else:
            acc = next(e.card for e in cfg.employees if e.no == r["payee"])
        ws.append([r["no"], r["date"].strftime("%Y-%m-%d"), r["payer"],
                   cfg.company_account, r["payee"], float(r["amount"]),
                   r["purpose"]])
    _style_sheet(ws, [22, 12, 20, 34, 22, 13, 50], num_cols=(6,))
    for i in range(2, ws.max_row + 1):
        ws.cell(row=i, column=2).number_format = "yyyy-mm-dd"
        ws.cell(row=i, column=6).number_format = "#,##0.00"

    # --- Sheet6 勾稽校验 ---
    ws = wb.create_sheet("勾稽校验")
    ws.append(["序号", "校验期间", "校验项", "表A金额（元）", "表B金额（元）",
               "差异（元）", "是否通过", "说明"])
    for i, c in enumerate(checks, 1):
        ws.append([i, c["month"], c["item"], float(c["a"]), float(c["b"]),
                   float(c["diff"]), "通过" if c["ok"] else "不通过", c["note"]])
    _style_sheet(ws, [6, 11, 52, 14, 14, 10, 9, 44], num_cols=(4, 5, 6))
    pass_n = sum(1 for c in checks if c["ok"])
    ws.append(["", "", f"合计 {len(checks)} 项，通过 {pass_n} 项，"
                      f"不通过 {len(checks) - pass_n} 项",
               "", "", "", "全部通过" if pass_n == len(checks) else "存在异常", ""])
    for j in range(1, 9):
        ws.cell(row=ws.max_row, column=j).font = Font(name="微软雅黑", size=10,
                                                      bold=True)

    # --- Sheet7 口径说明 ---
    from .notes import caliber_rows
    ws = wb.create_sheet("口径说明")
    for k, v in caliber_rows(cfg):
        ws.append([k, v])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 110
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=2):
        for c in row:
            c.font = BODY_FONT
            c.alignment = LEFT
            c.border = BORDER
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=2):
        if row[0].value and row[1].value in ("", None) and row[0].row > 1:
            row[0].font = Font(name="微软雅黑", size=10, bold=True)
    ws["A1"].font = Font(name="微软雅黑", size=13, bold=True, color="2F5496")

    wb.save(out_path)
    return len(checks), pass_n
