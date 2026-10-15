# -*- coding: utf-8 -*-
"""V-FLO 出口管制合规执行引擎 v2。

政策基准（集团合规原则）：
1) 西方单边制裁 ≠ 自动拒绝。中国与相关国家存在有限度的正常贸易与合作，
   V-FLO 采取「人工合规审核放行」：系统只升级、不自动否决，由合规官终审。
2) 重点把关：两用物项与敏感物项（中国《出口管制法》《两用物项出口管制条例》
   《两用物项出口管制清单》为主依据），无许可不得出口。
3) 硬闸仅保留国际与国内法红线：大规模杀伤性武器/军用最终用途 + 受控物项 → 禁止。
4) 规则优先、AI 辅助解释；不得依赖大模型做最终合规结论。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 国家维度：仅作风险提示，不自动否决（西方单边制裁参考名单）
# ---------------------------------------------------------------------------
WESTERN_SANCTIONS_REFERENCE = {
    "IR", "KP", "SY", "CU", "RU", "BY", "VE", "MM", "SD", "LY", "YE", "AF", "IQ", "LB",
}
# 受关注目的地（转运/转口风险较高）
WATCH_COUNTRIES = {"PK", "TR", "AE", "MY", "TH", "KZ", "UZ", "AM", "GE", "KG"}
# 与 V-FLO 业务相关的正常合作/有限合作目的地示例
NORMAL_COOP_COUNTRIES = {"RU", "BY", "KZ", "UZ", "IR", "IN", "TR", "AE", "SA", "IQ"}

# ---------------------------------------------------------------------------
# 物项维度（重点）：两用物项与敏感物项提示词表
# 对照《中国两用物项出口管制清单》大类，命中必须正式分类
# ---------------------------------------------------------------------------
# 核两用品及相关技术
NUCLEAR_HINTS = [
    "核燃料", "核反应", "核电", "核级", "nuclear", "气体离心", "铀浓缩",
    "uranium enrichment", "重水", "heavy water", "铀", "uranium",
    "钚", "plutonium", "同位素分离", "isotope separation", "辐照", "irradiation",
    "离心机", "centrifuge",  # 离心机 ≠ 离心泵
]
# 生化两用品
CHEMBIO_HINTS = [
    "化工武器", "chem", "生物", "bio", "前体", "precursor", "毒素", "toxin",
    "发酵罐", "防护服", "containment",
]
# 导弹相关
MISSILE_HINTS = [
    "导弹", "missile", "火箭", "rocket", "制导", "guidance", "惯性导航", "ins",
    "无人机", "uav", "推进剂", "propellant",
]
# 常规武器/军品
MILITARY_HINTS = [
    "军", "military", "武器", "weapon", "装甲", "armored", "雷达", "radar",
    "军规", "mil-spec", "军用", "弹药", "ammunition",
]
# 敏感工业与两用技术（泵阀/密封/驱动/材料 —— V-FLO 主业相关，必须重点分类）
INDUSTRIAL_DUAL_USE_HINTS = [
    "屏蔽泵", "sealless", "无泄漏泵", "磁力泵", "magnetic drive",
    "屏蔽电机", "canned motor", "变频", "VSD", "VFD", "伺服", "servo",
    "机械密封", "mechanical seal", "干气密封", "dry gas seal", "磁流体",
    "深冷", "cryogenic", "超高压", "ultra-high pressure", "高温气冷",
    "特种合金", "哈氏合金", "hastelloy", "因科镍", "inconel", "锆", "zirconium",
    "碳化硅", "SiC", "陶瓷密封", "轴承", "bearing",
    "离心机", "centrifuge", "压缩机", "compressor",
    "真空", "vacuum", "氟聚合物", "fluoropolymer", "聚酰亚胺",
]
# 石化成套/特定工艺（视最终用途可能受控）
PROCESS_HINTS = [
    "炼油", "refinery", "加氢", "hydrocracking", "重整", "reforming",
    "乙烯", "ethylene", "气体处理", "gas processing", "液化天然气", "LNG",
    "空分", "air separation", "氟化工", "煤化工",
]

# 最终用途红线（国际与国内法红线）
WMD_END_USE_KEYWORDS = [
    "核武", "nuclear weapon", "生化武器", "chemical weapon", "biological weapon",
    "导弹", "missile program", "大规模杀伤", "wmd",
]
MILITARY_END_USE_KEYWORDS = [
    "军用", "military", "国防", "defense", "部队", "armed forces", "weapons",
    "武器生产", "弹药", "军工厂",
]

# 通用红旗
RED_FLAG_RULES = [
    ("拒绝对最终用途作出说明", "客户回避最终用户/最终用途信息"),
    ("中间商异常", "收货方与最终用户不一致且无法合理解释"),
    ("与产品性能不匹配", "采购量/型号与民用场景明显不匹配"),
    ("军用或大规模杀伤性武器暗示", "技术参数或现场信息暗示军用/核/生化用途"),
    ("愿意支付现金溢价", "异常付款条件规避银行审查"),
    ("绕开正常安装调试", "拒绝安装、培训或售后服务"),
    ("目的地异常", "运抵国与最终用户所在国不一致且无合理解释"),
    ("敏感转运路线", "经高风险国家/地区转运且无合理解释"),
    ("刻意回避物项分类", "客户要求不写型号/不提供参数，阻碍出口管制分类"),
]


# ---------------------------------------------------------------------------
# 制裁名单筛查源（附件1 WBS T19：屏蔽源可插拔）
# 默认 LocalSanctionsProvider（本地参考名单+关键词）；配置 SANCTIONS_API_URL/KEY 后
# 切换为 HttpSanctionsProvider，调用正式名单服务，失败自动降级本地，不影响初筛主流程。
# ---------------------------------------------------------------------------
class SanctionsProvider:
    name = "base"

    def screen(self, customer_name: str, end_user: str, country_code: str) -> dict:
        """返回 {"hits": [str], "source": str}。"""
        raise NotImplementedError


class LocalSanctionsProvider(SanctionsProvider):
    name = "local-reference"

    def __init__(self, codes: set | None = None) -> None:
        # 西方制裁参考名单可配置（compliance_rules 表 country_list/western）
        self.codes = {c.upper() for c in codes} if codes else WESTERN_SANCTIONS_REFERENCE

    def screen(self, customer_name: str, end_user: str, country_code: str) -> dict:
        hits = []
        if country_code in self.codes:
            hits.append(f"目的地代码 {country_code} 出现在西方制裁参考名单（仅风险提示，不自动否决）")
        return {"hits": hits, "source": self.name}


class HttpSanctionsProvider(SanctionsProvider):
    name = "external-api"

    def __init__(self, url: str, api_key: str) -> None:
        self.url = url
        self.api_key = api_key

    def screen(self, customer_name: str, end_user: str, country_code: str) -> dict:
        import httpx
        payload = {"customer": customer_name, "end_user": end_user, "country": country_code}
        with httpx.Client(timeout=15) as client:
            resp = client.post(self.url, json=payload,
                               headers={"Authorization": f"Bearer {self.api_key}"})
            resp.raise_for_status()
            obj = resp.json() or {}
        hits = [str(h) for h in (obj.get("hits") or obj.get("matches") or [])]
        return {"hits": hits, "source": self.name}


def get_sanctions_provider() -> SanctionsProvider:
    from ..config import get_settings
    s = get_settings()
    if s.sanctions_api_url:
        return HttpSanctionsProvider(s.sanctions_api_url, s.sanctions_api_key)
    return LocalSanctionsProvider()


@dataclass
class CheckItem:
    code: str
    name: str
    required: bool
    status: str = "pending"
    note: str = ""


@dataclass
class ScreeningResult:
    country_risk: str = "unknown"
    sanctions_hit: str = "none"          # none/possible/confirmed（西方名单提示）
    item_control: str = "unknown"        # dual_use/controlled/unclear/civil
    item_category: str = "unknown"       # nuclear/chembio/missile/military/industrial/process/civil
    license_needed: str = "unknown"      # yes/no/unknown
    red_flags: list = field(default_factory=list)
    checklist: list = field(default_factory=list)
    decision: str = "pending"            # reject/manual_review/escalate/pending/pass
    decision_note: str = ""
    warnings: list = field(default_factory=list)


# 检查清单：与《开发方案_岗位KPI与出口管制升级版》§2.2「十二项检查清单」逐项对齐
BASE_CHECKLIST = [
    ("EXP-01", "客户/中间商/最终用户主体识别完整", True),
    ("EXP-02", "最终用途书面说明已获取", True),
    ("EXP-03", "目的地/运抵国/最终用户所在国一致或已解释", True),
    ("EXP-04", "制裁名单筛查（OFAC/BIS/UN/EU/中国不可靠实体）", True),
    ("EXP-05", "物项出口管制分类（EAR99 / 管控 / 两用）", True),
    ("EXP-06", "是否需要出口许可证", True),
    ("EXP-07", "技术资料外发边界确认（图纸/源码/工艺）", True),
    ("EXP-08", "合同出口管制与制裁条款已纳入", True),
    ("EXP-09", "红旗清单逐条核对", True),
    ("EXP-10", "合规官/授权人审批记录", True),
    ("EXP-11", "档案留存（≥5 年或按公司制度）", False),
    ("EXP-12", "最终用户/最终用途承诺书（EUC）", False),
]


def rules_from_constants() -> dict:
    """从模块常量组装规则集（与 compliance_rules.load_rules 同构；DB 未配置时的兜底）。"""
    return {
        "western_sanctions": set(WESTERN_SANCTIONS_REFERENCE),
        "watch_countries": set(WATCH_COUNTRIES),
        "normal_coop": set(NORMAL_COOP_COUNTRIES),
        "item_hints": {
            "nuclear": list(NUCLEAR_HINTS), "chembio": list(CHEMBIO_HINTS),
            "missile": list(MISSILE_HINTS), "military": list(MILITARY_HINTS),
            "industrial": list(INDUSTRIAL_DUAL_USE_HINTS), "process": list(PROCESS_HINTS),
        },
        "wmd_keywords": list(WMD_END_USE_KEYWORDS),
        "military_keywords": list(MILITARY_END_USE_KEYWORDS),
        "red_flag_rules": [(t, d) for t, d in RED_FLAG_RULES],
        "checklist": list(BASE_CHECKLIST),
        "decision_notes": {},
        "source": "default",
    }


def build_checklist(results: dict | None = None,
                    items: list | None = None) -> list[dict]:
    results = results or {}
    return [
        {"code": c, "name": n, "required": req, "status": results.get(c, "pending")}
        for c, n, req in (items or BASE_CHECKLIST)
    ]


def _norm_country(country: str) -> str:
    c = (country or "").strip().upper()
    mapping = {
        "中国": "CN", "俄罗斯": "RU", "伊朗": "IR", "朝鲜": "KP", "叙利亚": "SY",
        "古巴": "CU", "白俄罗斯": "BY", "委内瑞拉": "VE", "缅甸": "MM",
        "美国": "US", "德国": "DE", "印度": "IN", "巴基斯坦": "PK",
        "阿联酋": "AE", "土耳其": "TR", "哈萨克斯坦": "KZ", "乌兹别克斯坦": "UZ",
    }
    if c in mapping:
        return mapping[c]
    if len(c) == 2:
        return c
    return c[:2] if c else "XX"


def classify_item(product_desc: str, end_use: str = "",
                  hints: dict | None = None) -> tuple[str, str, list[str]]:
    """返回 (item_control, item_category, warnings)。重点：两用物项与敏感物项。

    hints：规则资产库 item_hints 类（load_rules 输出）。
    - hints=None：完全使用模块内置常量（向后兼容）；
    - hints 显式传入：以传入为准，缺键 = 该类别已停用/未配置（不再回退常量），
      保证合规官在 DB 中停用某类提示词立即生效。
    """
    if hints is None:
        hints = {
            "nuclear": NUCLEAR_HINTS, "chembio": CHEMBIO_HINTS, "missile": MISSILE_HINTS,
            "military": MILITARY_HINTS, "industrial": INDUSTRIAL_DUAL_USE_HINTS,
            "process": PROCESS_HINTS,
        }
    nuclear = hints.get("nuclear") or []
    chembio = hints.get("chembio") or []
    missile = hints.get("missile") or []
    military = hints.get("military") or []
    industrial = hints.get("industrial") or []
    process = hints.get("process") or []
    text = f"{product_desc} {end_use}".lower()
    warnings: list[str] = []

    def hit(words: list[str]) -> bool:
        return any(w.lower() in text for w in words)

    # 优先级：核/生化/导弹 > 军品 > 工业两用 > 工艺 > 民用
    if hit(nuclear):
        warnings.append("命中核两用品/相关技术提示，必须按《两用物项出口管制清单》核类条款分类")
        return "dual_use", "nuclear", warnings
    if hit(chembio):
        warnings.append("命中生化两用品提示，必须正式分类")
        return "dual_use", "chembio", warnings
    if hit(missile):
        warnings.append("命中导弹/无人系统相关提示，必须正式分类")
        return "dual_use", "missile", warnings
    if hit(military):
        warnings.append("命中军品/常规武器提示，须军品出口资质与许可判断")
        return "controlled", "military", warnings
    if hit(industrial):
        warnings.append(
            "【V-FLO重点】命中工业两用/敏感技术提示（泵/密封/驱动/特种材料等），"
            "必须由合规官对照《两用物项出口管制清单》逐项分类，不得以「民品」默认放行"
        )
        return "dual_use", "industrial", warnings
    if hit(process):
        warnings.append("石化/化工成套工艺提示：需结合最终用途判断是否落入两用管制范围")
        return "unclear", "process", warnings

    warnings.append("未命中受控提示词，但分类结论以合规官正式判定为准，不得仅凭本提示放行")
    return "civil?", "civil", warnings


def screen(
    customer_name: str,
    country: str,
    end_user: str,
    end_use: str,
    product_desc: str,
    hs_code: str = "",
    extra_red_flags: list[str] | None = None,
    middleman: str = "",
    arrival_country: str = "",
    end_user_country: str = "",
    sanctions_provider: SanctionsProvider | None = None,
    rules: dict | None = None,
) -> ScreeningResult:
    """出口管制初筛。结论仅供合规官人工审核，系统不替代放行权。

    rules：合规规则资产（compliance_rules.load_rules 的输出，DB 可配置）；
    None 时回退模块内置常量（rules_from_constants），二者经种子同源。
    规则语义：R 中存在的键以其为准（显式空集 = 已清空）；缺键才回退内置常量。
    """
    R = rules or rules_from_constants()
    western = R.get("western_sanctions", set(WESTERN_SANCTIONS_REFERENCE))
    watch = R.get("watch_countries", set(WATCH_COUNTRIES))
    wmd_kws = R.get("wmd_keywords", list(WMD_END_USE_KEYWORDS))
    mil_kws = R.get("military_keywords", list(MILITARY_END_USE_KEYWORDS))
    rf_rules = R.get("red_flag_rules", [(t, d) for t, d in RED_FLAG_RULES])
    notes = R.get("decision_notes", {})

    r = ScreeningResult()
    code = _norm_country(country)

    # 1) 国家风险：西方名单仅作提示，不自动否决
    if code in western:
        r.country_risk = "high" if code in {"IR", "KP", "SY", "CU"} else "medium"
    elif code in watch:
        r.country_risk = "medium"
    else:
        r.country_risk = "low"

    # 2) 制裁名单筛查（EXP-04）：屏蔽源可插拔（T19），外部源失败降级本地
    provider = sanctions_provider or get_sanctions_provider()
    if isinstance(provider, LocalSanctionsProvider) and rules:
        provider = LocalSanctionsProvider(codes=set(western))
    try:
        sres = provider.screen(customer_name, end_user, code)
        hits = list(sres.get("hits") or [])
        r.warnings.append(f"制裁名单筛查源：{sres.get('source')}")
    except Exception as e:  # noqa: BLE001 — 外部名单服务不可用不得阻断初筛
        hits = []
        if code in western:
            hits.append(f"目的地 {country or code} 出现在西方制裁参考名单（仅风险提示，不自动否决）")
        r.warnings.append(f"外部制裁名单服务不可用，已降级本地参考名单：{e}")
    use_text = f"{customer_name} {middleman} {end_user} {end_use}".lower()
    for kw in list(mil_kws) + list(wmd_kws):
        if kw.lower() in use_text:
            hits.append(f"最终用途/主体描述出现敏感关键词：{kw}")
    r.sanctions_hit = "possible" if hits else "none"
    for h in hits:
        r.warnings.append(h)

    # 3) 物项分类（重点；提示词表来自规则资产）
    item_control, item_cat, item_warns = classify_item(
        product_desc, end_use, hints=R.get("item_hints"))
    r.item_control = item_control
    r.item_category = item_cat
    r.warnings.extend(item_warns)

    # 4) 最终用途红线判定
    wmd = any(k.lower() in use_text for k in wmd_kws)
    military = any(k.lower() in use_text for k in mil_kws)

    # 5) 决策（V-FLO 政策）
    #    硬闸仅：大规模杀伤性武器用途 + 受控/两用物项 → 禁止
    #    两用/敏感物项 → 必须合规官分类+许可（escalate）
    #    西方制裁目的地 → 人工审核放行（manual_review）
    #    其他 → 完成清单后授权放行（pending）
    if wmd and item_control in ("dual_use", "controlled"):
        r.decision = "reject"
        r.license_needed = "yes"
        r.decision_note = notes.get("reject_wmd") or (
            "【硬闸】最终用途指向大规模杀伤性武器且物项属两用/受控范围，禁止出口。"
            "立即停止报价/签约/发运/技术外发，并上报合规官与管理层。"
        )
    elif military and item_control in ("dual_use", "controlled"):
        r.decision = "reject"
        r.license_needed = "yes"
        r.decision_note = notes.get("reject_military") or (
            "【硬闸】军用最终用途 + 两用/受控物项，禁止在未取得军品出口许可与合规官书面批准前出口。"
            "本系统默认拒绝，须走专项审批。"
        )
    elif item_control in ("dual_use", "controlled") or item_cat in (
        "nuclear", "chembio", "missile", "military", "industrial",
    ):
        r.decision = "escalate"
        r.license_needed = "unknown"
        r.decision_note = notes.get("escalate_dual_use") or (
            "【重点把关】两用物项/敏感物项：必须由合规官对照《两用物项出口管制清单》"
            "完成正式分类并判断是否需要出口许可证；无分类结论与许可判断不得签约/发运/外发技术资料。"
        )
    elif item_control == "unclear":
        r.decision = "escalate"
        r.license_needed = "unknown"
        r.decision_note = notes.get("escalate_unclear") or "物项性质不明（工艺成套类），必须人工分类确认后放行。"
    elif code in western:
        r.decision = "manual_review"
        r.license_needed = "unknown"
        r.decision_note = notes.get("manual_review_sanctions") or (
            "【人工审核放行】目的地出现在西方制裁参考名单。按集团原则："
            "中国与该国存在有限度正常合作，不自动拒绝；由合规官结合中国法规、"
            "最终用途、物项分类、支付与物流路径，决定是否放行/附加条件/否决。"
        )
    else:
        r.decision = "pending"
        r.license_needed = "no?"
        r.decision_note = notes.get("pending_default") or \
            "初筛未见阻断项；仍须完成检查清单、红旗核对与合规官审核后放行。"

    # 6) 红旗（附件1 §2.3：命中即升级，不得继续报价/签约）
    flags = []
    if not (end_user or "").strip():
        flags.append("未提供最终用户")
    if not (end_use or "").strip():
        flags.append("未提供最终用途")
    if (end_user or "").strip() and (customer_name or "").strip() \
            and end_user.strip() != customer_name.strip() and not (middleman or "").strip():
        flags.append("收货客户与最终用户不一致且未说明中间商角色")
    # EXP-03：目的地/运抵国/最终用户所在国一致性
    arr = _norm_country(arrival_country) if (arrival_country or "").strip() else ""
    euc = _norm_country(end_user_country) if (end_user_country or "").strip() else ""
    if arr and euc and arr != euc:
        flags.append("运抵国与最终用户所在国不一致且无合理解释")
    elif (arr and arr != code) or (euc and euc != code):
        r.warnings.append("目的地/运抵国/最终用户所在国不完全一致，请在审查单中作出解释（EXP-03）")
    for text_rule, desc in rf_rules:
        key = str(text_rule)[:2]
        if key and key in f"{end_use}{customer_name}{middleman}{product_desc}":
            flags.append(str(desc))
    if extra_red_flags:
        flags.extend([x for x in extra_red_flags if x])
    r.red_flags = flags

    # 红旗命中即升级复核（pending 与 manual_review 均升级；reject 硬闸不受影响）
    if flags and r.decision in ("pending", "manual_review"):
        r.decision = "escalate"
        r.decision_note = (r.decision_note or "") + " 存在红旗项，必须升级人工复核，红旗未关闭不得推进。"

    # 硬闸保护：WMD/军用+受控绝不可被降级
    if (wmd or military) and item_control in ("dual_use", "controlled"):
        r.decision = "reject"
        r.license_needed = "yes"

    r.checklist = build_checklist(items=R.get("checklist"))

    def _set(code_: str, ok: bool) -> None:
        for item in r.checklist:
            if item["code"] == code_:
                item["status"] = "pass" if ok else "fail"
                break

    # EXP-01 主体识别：客户 + 最终用户（有中间商时需已填写）
    if (customer_name or "").strip() and (end_user or "").strip():
        _set("EXP-01", True)
    # EXP-02 最终用途书面说明
    if (end_use or "").strip():
        _set("EXP-02", True)
    # EXP-03 国别一致性（一致或已解释）
    if code not in {"XX", ""} and not (arr and euc and arr != euc):
        _set("EXP-03", True)
    # EXP-04 制裁名单筛查（本次已执行）
    _set("EXP-04", not hits)
    # EXP-05 物项分类
    if r.item_control != "unknown":
        _set("EXP-05", True)
    # EXP-09 红旗逐条核对（本次已执行）
    _set("EXP-09", not flags)
    return r


def compliance_prompt_snippet() -> str:
    """场景提示词中强制注入的合规约束。"""
    return (
        "\n\n【出口管制合规强制约束 · V-FLO 政策版】\n"
        "1. 重点把关两用物项与敏感物项：涉及泵/密封/驱动/特种材料/工艺包时，"
        "必须提示「须对照《中国两用物项出口管制清单》正式分类」，不得以民品默认。\n"
        "2. 本输出不得包含可能构成技术出口的受控参数、图纸尺寸、工艺细节；"
        "技术数据须走合规审批后的内部通道。\n"
        "3. 西方制裁名单仅作风险提示；不得建议规避任何适用的中国法规与国际义务，"
        "也不得输出「如何绕开制裁」的路径。\n"
        "4. 涉及客户/最终用户/目的地的表述必须准确，不确定处标注[待合规确认]。\n"
        "5. 系统结论（含 manual_review）仅为初筛意见；最终放行由合规官人工书面决定。\n"
    )
