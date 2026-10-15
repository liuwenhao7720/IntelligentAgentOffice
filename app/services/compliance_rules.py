# -*- coding: utf-8 -*-
"""合规审查规则与资料资产（可调用配置）。

把原先硬编码在 export_control.py 的审查规则（国家名单/物项提示词/红线关键词/
红旗清单/检查清单/决策文案）与「选型软件」等资料，配置化入库（compliance_rules 表），
形成可调用资产：
- 审查引擎 screen() 经 load_rules() 读取 DB 规则（未配置时回退内置默认，二者同源）；
- 前端「出口管制」页签与审查单可 GET 规则/资料；compliance/admin 可在线维护；
- 工作台生成不直接读规则，只调用项目审查结果（审查前移，见 routers/compliance.py）。
"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import ComplianceRule

# ---------------------------------------------------------------------------
# 内置默认规则（与 export_control.py 原硬编码同源；DB 无配置时的兜底 + 种子来源）
# ---------------------------------------------------------------------------
DEFAULT_RULES: list[dict] = [
    # ---- 国家名单 ----
    {"category": "country_list", "code": "western", "name": "西方制裁参考名单（仅风险提示，不自动否决）",
     "value": {"codes": ["IR", "KP", "SY", "CU", "RU", "BY", "VE", "MM", "SD", "LY", "YE", "AF", "IQ", "LB"]},
     "description": "集团原则：中国与相关国家存在有限度正常贸易，一律人工合规审核放行", "sort": 1},
    {"category": "country_list", "code": "watch", "name": "受关注目的地（转运/转口风险较高）",
     "value": {"codes": ["PK", "TR", "AE", "MY", "TH", "KZ", "UZ", "AM", "GE", "KG"]},
     "description": "途经/运抵这些国家需重点核对物流路径", "sort": 2},
    {"category": "country_list", "code": "normal_coop", "name": "正常/有限合作目的地示例",
     "value": {"codes": ["RU", "BY", "KZ", "UZ", "IR", "IN", "TR", "AE", "SA", "IQ"]},
     "description": "有限度正常合作目的地参考", "sort": 3},
    # ---- 物项提示词表（对照《中国两用物项出口管制清单》大类） ----
    {"category": "item_hints", "code": "nuclear", "name": "核两用品及相关技术",
     "value": {"words": ["核燃料", "核反应", "核电", "核级", "nuclear", "气体离心", "铀浓缩",
                         "uranium enrichment", "重水", "heavy water", "铀", "uranium",
                         "钚", "plutonium", "同位素分离", "isotope separation", "辐照", "irradiation",
                         "离心机", "centrifuge"]},
     "description": "命中必须按核类条款正式分类（注意：离心机≠离心泵）", "sort": 11},
    {"category": "item_hints", "code": "chembio", "name": "生化两用品",
     "value": {"words": ["化工武器", "chem", "生物", "bio", "前体", "precursor", "毒素", "toxin",
                         "发酵罐", "防护服", "containment"]},
     "description": "命中必须正式分类", "sort": 12},
    {"category": "item_hints", "code": "missile", "name": "导弹相关",
     "value": {"words": ["导弹", "missile", "火箭", "rocket", "制导", "guidance", "惯性导航", "ins",
                         "无人机", "uav", "推进剂", "propellant"]},
     "description": "命中必须正式分类", "sort": 13},
    {"category": "item_hints", "code": "military", "name": "常规武器/军品",
     "value": {"words": ["军", "military", "武器", "weapon", "装甲", "armored", "雷达", "radar",
                         "军规", "mil-spec", "军用", "弹药", "ammunition"]},
     "description": "须军品出口资质与许可判断", "sort": 14},
    {"category": "item_hints", "code": "industrial", "name": "敏感工业与两用技术（V-FLO 主业重点）",
     "value": {"words": ["屏蔽泵", "sealless", "无泄漏泵", "磁力泵", "magnetic drive",
                         "屏蔽电机", "canned motor", "变频", "VSD", "VFD", "伺服", "servo",
                         "机械密封", "mechanical seal", "干气密封", "dry gas seal", "磁流体",
                         "深冷", "cryogenic", "超高压", "ultra-high pressure", "高温气冷",
                         "特种合金", "哈氏合金", "hastelloy", "因科镍", "inconel", "锆", "zirconium",
                         "碳化硅", "SiC", "陶瓷密封", "轴承", "bearing",
                         "离心机", "centrifuge", "压缩机", "compressor",
                         "真空", "vacuum", "氟聚合物", "fluoropolymer", "聚酰亚胺"]},
     "description": "泵/密封/驱动/特种材料：必须由合规官逐项分类，不得以民品默认放行", "sort": 15},
    {"category": "item_hints", "code": "process", "name": "石化成套/特定工艺",
     "value": {"words": ["炼油", "refinery", "加氢", "hydrocracking", "重整", "reforming",
                         "乙烯", "ethylene", "气体处理", "gas processing", "液化天然气", "LNG",
                         "空分", "air separation", "氟化工", "煤化工"]},
     "description": "视最终用途可能受控，需人工判断", "sort": 16},
    # ---- 最终用途红线 ----
    {"category": "end_use_redline", "code": "wmd", "name": "大规模杀伤性武器用途红线",
     "value": {"words": ["核武", "nuclear weapon", "生化武器", "chemical weapon", "biological weapon",
                         "导弹", "missile program", "大规模杀伤", "wmd"]},
     "description": "WMD 用途 + 受控物项 = 硬性禁止（国际与国内法红线）", "sort": 21},
    {"category": "end_use_redline", "code": "military", "name": "军用最终用途红线",
     "value": {"words": ["军用", "military", "国防", "defense", "部队", "armed forces", "weapons",
                         "武器生产", "弹药", "军工厂"]},
     "description": "军用用途 + 两用/受控物项 = 默认拒绝，须专项审批", "sort": 22},
    # ---- 决策规则文案 ----
    {"category": "decision_note", "code": "reject_wmd", "name": "硬闸：WMD 用途",
     "value": {"text": "【硬闸】最终用途指向大规模杀伤性武器且物项属两用/受控范围，禁止出口。"
                       "立即停止报价/签约/发运/技术外发，并上报合规官与管理层。"}, "sort": 31},
    {"category": "decision_note", "code": "reject_military", "name": "硬闸：军用用途",
     "value": {"text": "【硬闸】军用最终用途 + 两用/受控物项，禁止在未取得军品出口许可与合规官书面批准前出口。"
                       "本系统默认拒绝，须走专项审批。"}, "sort": 32},
    {"category": "decision_note", "code": "escalate_dual_use", "name": "升级：两用/敏感物项",
     "value": {"text": "【重点把关】两用物项/敏感物项：必须由合规官对照《两用物项出口管制清单》"
                       "完成正式分类并判断是否需要出口许可证；无分类结论与许可判断不得签约/发运/外发技术资料。"},
     "sort": 33},
    {"category": "decision_note", "code": "escalate_unclear", "name": "升级：物项性质不明",
     "value": {"text": "物项性质不明（工艺成套类），必须人工分类确认后放行。"}, "sort": 34},
    {"category": "decision_note", "code": "manual_review_sanctions", "name": "人工审核：西方制裁目的地",
     "value": {"text": "【人工审核放行】目的地出现在西方制裁参考名单。按集团原则：中国与该国存在有限度正常合作，"
                       "不自动拒绝；由合规官结合中国法规、最终用途、物项分类、支付与物流路径，"
                       "决定是否放行/附加条件/否决。"}, "sort": 35},
    {"category": "decision_note", "code": "pending_default", "name": "默认：未见阻断项",
     "value": {"text": "初筛未见阻断项；仍须完成检查清单、红旗核对与合规官审核后放行。"}, "sort": 36},
]

# 红旗清单（trigger 前 2 字命中即记红旗；保持与原 RED_FLAG_RULES 一致）
DEFAULT_RED_FLAGS: list[dict] = [
    {"category": "red_flag", "code": f"RF-{i + 1:02d}", "name": desc,
     "value": {"trigger": trigger, "desc": desc}, "sort": 41 + i}
    for i, (trigger, desc) in enumerate([
        ("拒绝对最终用途作出说明", "客户回避最终用户/最终用途信息"),
        ("中间商异常", "收货方与最终用户不一致且无法合理解释"),
        ("与产品性能不匹配", "采购量/型号与民用场景明显不匹配"),
        ("军用或大规模杀伤性武器暗示", "技术参数或现场信息暗示军用/核/生化用途"),
        ("愿意支付现金溢价", "异常付款条件规避银行审查"),
        ("绕开正常安装调试", "拒绝安装、培训或售后服务"),
        ("目的地异常", "运抵国与最终用户所在国不一致且无合理解释"),
        ("敏感转运路线", "经高风险国家/地区转运且无合理解释"),
        ("刻意回避物项分类", "客户要求不写型号/不提供参数，阻碍出口管制分类"),
    ])
]

# 十二项检查清单（与《岗位KPI与出口管制升级版》§2.2 对齐）
DEFAULT_CHECKLIST: list[dict] = [
    {"category": "checklist", "code": code, "name": name,
     "value": {"required": required}, "sort": 51 + i}
    for i, (code, name, required) in enumerate([
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
    ])
]

# 资料资产（选型软件/法规文件/模板等，可在审查与工作台中调用）
DEFAULT_RESOURCES: list[dict] = [
    {"category": "resource", "code": "RES-SW-PUMPSEL", "name": "屏蔽泵选型软件（PumpSelect）",
     "value": {"type": "软件", "link": "\\\\fileserver\\engineering\\PumpSelect",
               "applicable": "售前选型/项目初步分析：输入工况参数自动生成候选机型与数据表",
               "version": "v3.2"},
     "description": "项目初步分析阶段的选型工具；选型结论截图随审查单归档", "sort": 61},
    {"category": "resource", "code": "RES-DOC-DUALUSE", "name": "《中国两用物项出口管制清单》",
     "value": {"type": "文档", "link": "http://www.mofcom.gov.cn/（商务部最新公告为准）",
               "applicable": "物项分类（EXP-05）：合规官对照分类的唯一依据", "version": "现行有效"},
     "description": "两用物项分类法定依据", "sort": 62},
    {"category": "resource", "code": "RES-DOC-ECL", "name": "《中华人民共和国出口管制法》",
     "value": {"type": "文档", "link": "http://www.npc.gov.cn/",
               "applicable": "全部审查：上位法依据", "version": "2020 施行"},
     "description": "出口管制上位法", "sort": 63},
    {"category": "resource", "code": "RES-TPL-EUC", "name": "最终用户/最终用途承诺书（EUC）模板",
     "value": {"type": "模板", "link": "\\\\fileserver\\compliance\\templates\\EUC-中英双语.docx",
               "applicable": "EXP-12：审查通过前由客户签署", "version": "v2.1"},
     "description": "可用场景卡 SC-EXP-002 起草，再套本模板签署", "sort": 64},
    {"category": "resource", "code": "RES-DOC-REDFLAG", "name": "红旗识别手册（BIS Red Flags 中译）",
     "value": {"type": "文档", "link": "\\\\fileserver\\compliance\\红旗识别手册.pdf",
               "applicable": "EXP-09：红旗清单逐条核对的培训依据", "version": "现行"},
     "description": "红旗培训与核对手册", "sort": 65},
]

ALL_DEFAULTS = DEFAULT_RULES + DEFAULT_RED_FLAGS + DEFAULT_CHECKLIST + DEFAULT_RESOURCES

CATEGORY_LABELS = {
    "country_list": "国家名单", "item_hints": "物项提示词表", "end_use_redline": "最终用途红线",
    "red_flag": "红旗规则", "checklist": "检查清单", "decision_note": "决策规则文案",
    "resource": "资料资产（软件/文档/模板）",
}

# 进程内缓存（规则极少变动；60s TTL，维护操作立即失效）
_CACHE: dict = {"at": 0.0, "rules": None}
_CACHE_TTL = 60


def invalidate_cache() -> None:
    _CACHE["at"] = 0.0
    _CACHE["rules"] = None


def seed_compliance_rules(db: Session) -> int:
    """幂等种子：把内置默认规则写入 DB（已存在的 category+code 跳过）。"""
    existing = {(r.category, r.code) for r in db.execute(
        select(ComplianceRule.category, ComplianceRule.code)).all()}
    created = 0
    for spec in ALL_DEFAULTS:
        if (spec["category"], spec["code"]) in existing:
            continue
        db.add(ComplianceRule(
            category=spec["category"], code=spec["code"], name=spec["name"],
            value=spec["value"], description=spec.get("description", ""),
            sort=spec.get("sort", 0), enabled=True, updated_by="system-seed",
        ))
        created += 1
    if created:
        db.commit()
        invalidate_cache()
    return created


def load_rules(db: Session, use_cache: bool = True) -> dict:
    """加载启用的规则 → 审查引擎可用的结构（DB 缺失的键回退内置默认，保证可运行）。

    返回：
    {
      western_sanctions: set, watch_countries: set, normal_coop: set,
      item_hints: {nuclear: [...], ...},
      wmd_keywords: [...], military_keywords: [...],
      red_flag_rules: [(trigger, desc), ...],
      checklist: [(code, name, required), ...],
      decision_notes: {code: text},
      source: "db" / "default" / "mixed",
    }
    """
    now = time.monotonic()
    if use_cache and _CACHE["rules"] is not None and now - _CACHE["at"] < _CACHE_TTL:
        return _CACHE["rules"]

    rows = db.execute(
        select(ComplianceRule).where(ComplianceRule.enabled == True)  # noqa: E712
        .order_by(ComplianceRule.sort)
    ).scalars().all()
    by_cat: dict[str, dict[str, dict]] = {}
    for r in rows:
        by_cat.setdefault(r.category, {})[r.code] = r.value or {}

    def _codes(cat: str, code: str, default_codes: list[str]) -> set:
        v = by_cat.get(cat, {}).get(code)
        if v and isinstance(v.get("codes"), list):
            return {str(c).upper() for c in v["codes"]}
        return {c.upper() for c in default_codes}

    def _hints(cat: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for code, v in by_cat.get(cat, {}).items():
            if isinstance(v.get("words"), list):
                out[code] = [str(w) for w in v["words"]]
        return out

    def _defaults(cat: str) -> dict[str, dict]:
        return {d["code"]: d["value"] for d in ALL_DEFAULTS if d["category"] == cat}

    item_hints = _hints("item_hints") or {
        c: list(v["words"]) for c, v in _defaults("item_hints").items()}
    # 整类无启用行才回退默认；类内缺键 = 该项已停用（不再回退该类常量）
    end_red = _hints("end_use_redline")
    if not end_red:
        end_red = {c: list(v["words"]) for c, v in _defaults("end_use_redline").items()}
    rf_rows = by_cat.get("red_flag") or {}
    red_flags = [(str(v.get("trigger", "")), str(v.get("desc", "")))
                 for k, v in rf_rows.items() if v.get("trigger")]
    if not red_flags:
        red_flags = [(d["value"]["trigger"], d["value"]["desc"]) for d in DEFAULT_RED_FLAGS]
    rf_rows = by_cat.get("red_flag") or {}
    red_flags = [(str(v.get("trigger", "")), str(v.get("desc", "")))
                 for k, v in rf_rows.items() if v.get("trigger")]
    if not red_flags:
        red_flags = [(d["value"]["trigger"], d["value"]["desc"]) for d in DEFAULT_RED_FLAGS]
    # 检查清单：以种子清单的顺序/名称为基线，DB 行按 code 覆盖（required 可调、可新增项）
    name_by_code = {r.code: r.name for r in rows if r.category == "checklist"}
    cl_rows = by_cat.get("checklist") or {}
    checklist: list[tuple[str, str, bool]] = []
    for d in DEFAULT_CHECKLIST:
        code = d["code"]
        v = cl_rows.pop(code, None)
        checklist.append((code,
                          name_by_code.get(code, d["name"]),
                          bool((v or {}).get("required", d["value"]["required"]))))
    for code, v in cl_rows.items():  # DB 新增清单项追加在尾部
        checklist.append((code, name_by_code.get(code, code),
                          bool((v or {}).get("required", True))))
    notes = {code: str(v.get("text", "")) for code, v in by_cat.get("decision_note", {}).items()}
    for d in DEFAULT_RULES:
        if d["category"] == "decision_note":
            notes.setdefault(d["code"], d["value"]["text"])

    rules = {
        "western_sanctions": _codes("country_list", "western",
                                    ["IR", "KP", "SY", "CU", "RU", "BY", "VE", "MM", "SD", "LY", "YE", "AF", "IQ", "LB"]),
        "watch_countries": _codes("country_list", "watch",
                                  ["PK", "TR", "AE", "MY", "TH", "KZ", "UZ", "AM", "GE", "KG"]),
        "normal_coop": _codes("country_list", "normal_coop",
                              ["RU", "BY", "KZ", "UZ", "IR", "IN", "TR", "AE", "SA", "IQ"]),
        "item_hints": item_hints,
        "wmd_keywords": end_red.get("wmd", []),
        "military_keywords": end_red.get("military", []),
        "red_flag_rules": red_flags,
        "checklist": checklist,
        "decision_notes": notes,
        "source": "db" if rows else "default",
    }
    _CACHE["at"] = now
    _CACHE["rules"] = rules
    return rules


# ---------------------------------------------------------------------------
# 项目合规状态（审查前移后，工作台只读取此结果，不重复审查）
# ---------------------------------------------------------------------------
# 状态口径：none 未审查 / reviewing 已提交待终审 / escalated 升级复核中 /
#           approved 已放行 / rejected 已否决
def project_compliance_state(check) -> dict:
    """ExportCheck（或 None）→ 工作台可读的项目合规状态摘要。"""
    if check is None:
        return {"state": "none", "case_no": "", "decision": "", "status": "",
                "reviewed_by": "", "decision_note": "",
                "message": "该项目尚未完成合规审查。请在项目初步分析阶段发起合规初筛，"
                           "由合规官终审后，工作台自动引用审查结论（不重复审查）。"}
    decision = check.decision or ""
    status = check.status or ""
    if status == "approved" and decision in ("pass", "manual_review"):
        state = "approved"
        msg = f"合规审查已放行（{check.case_no}，{decision}），可直接开展工作。"
    elif status == "rejected" or decision == "reject":
        state = "rejected"
        msg = f"合规审查已否决（{check.case_no}）：禁止报价/签约/发运/技术外发。"
    elif decision == "escalate":
        state = "escalated"
        msg = f"审查升级复核中（{check.case_no}）：两用物项须合规官完成正式分类后方可推进。"
    else:
        state = "reviewing"
        msg = f"审查单已提交、待合规官终审（{check.case_no}）。"
    return {"state": state, "case_no": check.case_no, "decision": decision,
            "status": status, "reviewed_by": check.reviewed_by or "",
            "decision_note": check.decision_note or "",
            "item_control": check.item_control or "", "country_risk": check.country_risk or "",
            "message": msg}
