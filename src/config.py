# -*- coding: utf-8 -*-
"""配置层：中国口径样例数据生成器的全部可配参数。

设计原则：
- 城市 / 年度 / 期间 / 人数 / 各险种比例 / 公积金比例 均可配置；
- 金额一律使用 Decimal，保留 2 位小数（ROUND_HALF_UP）；
- 人名、证件号、银行卡号、账号全部为虚构脱敏样例，不含任何真实个人信息。
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Tuple

D = Decimal

Q2 = Decimal("0.01")
Q1 = Decimal("1")


def D_(x) -> Decimal:
    return Decimal(str(x))


def r2(x) -> Decimal:
    """四舍五入保留 2 位小数（ROUND_HALF_UP）。"""
    return D_(x).quantize(Q2, rounding="ROUND_HALF_UP")


def r1(x) -> Decimal:
    """四舍五入到元（公积金月缴存额按北京规则取整）。"""
    return D_(x).quantize(Q1, rounding="ROUND_HALF_UP")


@dataclass
class Employee:
    """员工花名册条目（全部信息虚构脱敏）。"""
    no: str                       # 员工编号，如 员工01
    name: str                     # 脱敏姓名占位，如 王*敏
    salary: Decimal               # 月薪（元）
    deduct: Decimal               # 专项附加扣除合计（元/月）
    id_no: str                    # 脱敏证件号，如 110***4127
    card: str                     # 银行卡号（虚构）
    hire: str                     # 入职日期 YYYY-MM-DD
    leave: Optional[str] = None   # 离职日期，在职为 None
    note: str = ""                # 花名册备注（口径说明）


@dataclass
class Transition:
    """社保年度基数调整过渡期（如北京 2025：7-8 月按旧下限预缴、10 月统一补差）。

    触发规则（通用）：月薪低于新下限的员工，预缴月按 max(月薪, 旧下限) 核定，
    settle_month 在该员工当月工资中一次性补扣个人部分差额。
    """
    old_lower: Decimal            # 旧年度缴费基数下限
    prepay_months: List[Tuple[int, int]]   # 按旧口径预缴的费款所属月
    settle_month: Tuple[int, int]          # 统一补差、补收的费款/征期月


@dataclass
class Config:
    # ---- 主体信息（虚构）----
    company: str                  # 公司全称
    tax_authority: str            # 社保费征收机关（2024 起北京为税务部门）
    hf_center: str                # 公积金管理中心
    company_account: str          # 公司银行账号（虚构）
    tax_account: str              # 税务社保费专户（虚构）
    hf_account: str               # 公积金汇缴专户（虚构）

    # ---- 社保参数 ----
    social_base_upper: Decimal    # 缴费基数上限
    social_base_lower: Decimal    # 缴费基数下限
    rate_pension_corp: Decimal    # 养老 单位
    rate_pension_ind: Decimal     # 养老 个人
    rate_medical_corp: Decimal    # 基本医疗 单位
    rate_maternity_corp: Decimal  # 生育 单位（并入医疗合并征缴，仍单列比例）
    rate_medical_ind: Decimal     # 医疗 个人
    djb_individual: Decimal       # 大额医疗互助 个人固定额（元/月）
    rate_unemployment_corp: Decimal
    rate_unemployment_ind: Decimal
    rate_injury_corp: Decimal     # 工伤 单位（按行业基准费率取值）

    # ---- 公积金参数 ----
    hf_rate: Decimal              # 单位/个人缴存比例（同一比例）
    hf_base_upper: Decimal
    hf_base_lower: Decimal

    # ---- 个税参数（累计预扣法）----
    tax_threshold: Decimal        # 每月减除费用（起征点）
    tax_table: List[Tuple[Optional[Decimal], Decimal, Decimal]]
    # (级距上限, 税率, 速算扣除数)；上限 None 表示最后一档

    # ---- 期间 ----
    start_year: int               # 费款起始年
    start_month: int              # 费款起始月
    n_months: int                 # 费款所属月数量

    # ---- 资金节奏 ----
    pay_day: int = 10             # 工资代发日（次月发放上月工资）
    social_day: int = 12          # 社保划扣日（当月参保、次月缴费）
    hf_day: int = 15              # 公积金汇缴日（当月汇缴当月）

    # ---- 过渡期（无则 None）----
    transition: Optional[Transition] = None

    # ---- 花名册 ----
    employees: List[Employee] = field(default_factory=list)

    def periods(self) -> List[Tuple[int, int]]:
        """费款所属月列表。"""
        out = []
        y, m = self.start_year, self.start_month
        for _ in range(self.n_months):
            out.append((y, m))
            m += 1
            if m == 13:
                y, m = y + 1, 1
        return out


def beijing_2025_config() -> Config:
    """北京 2025 社保年度 / 2025 住房公积金年度默认配置（2025-07 ~ 2026-06）。

    参数来源（官方公开数据优先，详见 README「口径来源」）：
    - 社保基数上下限 35811/7162：京人社发〔2025〕11号（2025-09-17 发布，自 2025-07 执行）
    - 过渡期：7-8 月费款按 2024 年度下限 6821 预缴，10 月统一补差（官方通告原文规则）
    - 公积金：北京住房公积金管理中心 2025 年度通知（2025-09-18 发布），比例取 12%
    - 个税：累计预扣法（税务总局公告 2018 年第 61 号）
    """
    tax_table = [
        (D(36000), D("0.03"), D(0)),
        (D(144000), D("0.10"), D(2520)),
        (D(300000), D("0.20"), D(16920)),
        (D(420000), D("0.25"), D(31920)),
        (D(660000), D("0.30"), D(52920)),
        (D(960000), D("0.35"), D(85920)),
        (None, D("0.45"), D(181920)),
    ]
    employees = [
        Employee("员工01", "王*敏", D(25000), D(4500), "110***4127",
                 "6222 0210 5501 4127", "2023-03-01",
                 note="专项附加扣除：住房租金1500＋赡养老人3000"),
        Employee("员工02", "刘*强", D(7000), D(1500), "110***8863",
                 "6222 0210 5502 8863", "2024-06-01",
                 note=("月薪7000元低于2025年度社保基数下限7162元，按7162元核定；"
                       "2025年7-8月费款按旧下限6821元预缴、10月补差；"
                       "专项附加扣除：住房租金1500")),
        Employee("员工03", "陈*娟", D(18000), D(5000), "110***3341",
                 "6222 0210 5503 3341", "2023-05-01", leave="2026-03-20",
                 note=("2026-03-20 离职，离职当月社保仍缴、次月停；"
                       "专项附加扣除：子女教育2000＋赡养老人3000")),
        Employee("员工04", "杨*磊", D(12000), D(1500), "110***9702",
                 "6222 0210 5504 9702", "2024-01-01",
                 note="专项附加扣除：住房租金1500"),
        Employee("员工05", "赵*静", D(9500), D(0), "110***5618",
                 "6222 0210 5505 5618", "2024-09-01",
                 note="无专项附加扣除"),
        Employee("员工06", "周*杰", D(15000), D(3000), "110***2475",
                 "6222 0210 5506 2475", "2023-10-01",
                 note="专项附加扣除：赡养老人3000"),
        Employee("员工07", "吴*婷", D(22000), D(1500), "110***6039",
                 "6222 0210 5507 6039", "2026-01-12",
                 note="2026-01-12 入职；专项附加扣除：住房租金1500"),
        Employee("员工08", "郑*军", D(8000), D(0), "110***1234",
                 "6222 0210 5508 1234", "2025-05-01",
                 note="月薪8000元＞下限7162元，按实际工资核定（不触发下限封顶）"),
    ]
    return Config(
        company="北京虾米科技有限公司",
        tax_authority="国家税务总局北京市税务局",
        hf_center="北京住房公积金管理中心",
        company_account="0200 2319 0980 5506 321",
        tax_account="0200 2310 0000 0000 TAX（税务社保费专户·虚构）",
        hf_account="0200 2310 0000 0001 GJJ（公积金汇缴专户·虚构）",
        social_base_upper=D(35811),
        social_base_lower=D(7162),
        rate_pension_corp=D("0.16"),
        rate_pension_ind=D("0.08"),
        rate_medical_corp=D("0.09"),
        rate_maternity_corp=D("0.008"),
        rate_medical_ind=D("0.02"),
        djb_individual=D(3),
        rate_unemployment_corp=D("0.005"),
        rate_unemployment_ind=D("0.005"),
        rate_injury_corp=D("0.004"),
        hf_rate=D("0.12"),
        hf_base_upper=D(35811),
        hf_base_lower=D(2540),
        tax_threshold=D(5000),
        tax_table=tax_table,
        start_year=2025,
        start_month=7,
        n_months=12,
        transition=Transition(
            old_lower=D(6821),
            prepay_months=[(2025, 7), (2025, 8)],
            settle_month=(2025, 10),
        ),
        employees=employees,
    )
