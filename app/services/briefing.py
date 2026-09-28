# -*- coding: utf-8 -*-
"""简道云必做动作自动化：早宣 / 晚总 / 周计划 / 周总结 / 项目结项。

设计原则：
1. 员工只用口语化要点填空（或直接粘贴会话/文件夹资料）；
2. 系统生成符合简道云字段与「AI 评分」口径的规范文本；
3. 一键推送到简道云（先预览，人工确认后推送）；
4. 同步生成企微可发的短版（早宣/晚总卡片）。
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from ..services.model_gateway import gateway
from ..services.jdy import build_jdy_knowledge, build_jdy_task, jdy


def _today() -> str:
    return date.today().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 早宣：当日任务规划
# ---------------------------------------------------------------------------
def build_morning_plan(
    name: str,
    dept: str,
    tasks_raw: str,
    focus: str = "",
    blockers: str = "",
) -> dict:
    """生成早宣稿 + 简道云任务数据。"""
    prompt = (
        "你是 V-FLO 部门早宣助理。根据员工口述的今日任务，生成规范早宣稿与可录入简道云的任务规划。\n"
        f"姓名：{name}\n部门：{dept}\n日期：{_today()}\n"
        f"今日任务口述：\n{tasks_raw}\n"
        f"重点/难点：{focus or '无'}\n"
        f"需要协调：{blockers or '无'}\n\n"
        "输出两部分：\n"
        "【早宣稿】口语但专业，3–6 条，每条含：做什么/完成标准/时间点。\n"
        "【任务表】Markdown 表：任务名称|开始|截止|优先级|所属项目|完成标准。\n"
        "要求：任务名称具体可考核；时间点明确；避免“处理一下”类空话。"
    )
    result = gateway.chat(
        [{"role": "system", "content": "你是项目管理与计划写作专家。"},
         {"role": "user", "content": prompt}],
        model="mimo",
        temperature=0.3,
    )
    return {
        "type": "morning",
        "date": _today(),
        "title": f"早宣 {name} {_today()}",
        "content": result.text,
        "wecom_card": _extract_section(result.text, "早宣稿"),
        "jdy_payload": build_jdy_task(
            title=f"【早宣】{name} {_today()} 任务规划",
            start=_today(),
            due=_today(),
            owner=name,
            priority="高",
            category="团队培养" if False else "日常工作",
            description=result.text[:2000],
        ),
    }


# ---------------------------------------------------------------------------
# 晚总：当日完成情况与问题清单
# ---------------------------------------------------------------------------
def build_evening_review(
    name: str,
    dept: str,
    done_raw: str,
    issues_raw: str = "",
    tomorrow: str = "",
) -> dict:
    prompt = (
        "你是 V-FLO 晚总助理。根据员工口述，生成规范晚总（完成情况 + 问题清单 + 明日安排）。\n"
        f"姓名：{name}\n部门：{dept}\n日期：{_today()}\n"
        f"今日完成：\n{done_raw}\n"
        f"问题与未完成：{issues_raw or '无'}\n"
        f"明日计划：{tomorrow or '待定'}\n\n"
        "输出：\n【晚总稿】1. 今日完成（对照早宣，标注完成/部分/延期）2. 问题清单（问题|影响|需要谁协调|建议解决时限）"
        "3. 明日三条重点 4. 给领导一句话总结。\n"
        "要求：完成情况可核对；问题不回避；明日计划到时间点。"
    )
    result = gateway.chat(
        [{"role": "system", "content": "你是日报与问题管理专家。"},
         {"role": "user", "content": prompt}],
        model="mimo",
        temperature=0.3,
    )
    return {
        "type": "evening",
        "date": _today(),
        "title": f"晚总 {name} {_today()}",
        "content": result.text,
        "wecom_card": _extract_section(result.text, "晚总稿"),
        "jdy_payload": build_jdy_task(
            title=f"【晚总】{name} {_today()}",
            start=_today(),
            due=_today(),
            owner=name,
            priority="高",
            category="日常工作",
            description=result.text[:2000],
        ),
    }


# ---------------------------------------------------------------------------
# 周计划 / 周总结
# ---------------------------------------------------------------------------
def build_weekly_plan(name: str, dept: str, goals_raw: str, projects_raw: str = "") -> dict:
    prompt = (
        "你是 V-FLO 周计划助理。生成部门周计划（可录入简道云）。\n"
        f"姓名：{name}\n部门：{dept}\n"
        f"本周目标口述：\n{goals_raw}\n"
        f"涉及项目：{projects_raw or '无'}\n\n"
        "输出：\n【周计划稿】本周三个目标（可量化）+ 每日任务分解表（周一至周五）"
        "+ 风险与需要的支持 + 本周验收标准。\n"
        "【任务表】可直接录简道云：任务名称|起止|优先级|所属项目。"
    )
    result = gateway.chat(
        [{"role": "system", "content": "你是周计划管理专家。"},
         {"role": "user", "content": prompt}],
        model="deepseek",
        temperature=0.3,
    )
    return {
        "type": "weekly_plan",
        "date": _today(),
        "title": f"周计划 {name} {_today()}",
        "content": result.text,
        "wecom_card": _extract_section(result.text, "周计划稿"),
        "jdy_payload": build_jdy_task(
            title=f"【周计划】{name} {_today()}",
            start=_today(),
            due=_today(),
            owner=name,
            priority="最高",
            category="日常工作",
            description=result.text[:2000],
        ),
    }


def build_weekly_summary(name: str, dept: str, done_raw: str, issues_raw: str = "") -> dict:
    prompt = (
        "你是 V-FLO 周总结助理。对照“价值/流程/连接/优化”四维与 AI 评分口径（技术深度、"
        "问题解决彻底性、方案可维护性），写高质量周总结。\n"
        f"姓名：{name}\n部门：{dept}\n"
        f"本周完成：\n{done_raw}\n问题：{issues_raw or '无'}\n\n"
        "输出：\n【周总结稿】1. 本周成果（数据说话）2. 与目标对照表 3. 问题与根因 4. "
        "可沉淀经验（写成可入库条目）5. 下周计划 6. 需要的支持。\n"
        "文风：体现技术深度与可维护性，避免流水账。"
    )
    result = gateway.chat(
        [{"role": "system", "content": "你是高质量周报与知识沉淀专家。"},
         {"role": "user", "content": prompt}],
        model="kimi",
        temperature=0.3,
    )
    return {
        "type": "weekly_summary",
        "date": _today(),
        "title": f"周总结 {name} {_today()}",
        "content": result.text,
        "wecom_card": _extract_section(result.text, "周总结稿"),
        "jdy_payload": build_jdy_task(
            title=f"【周总结】{name} {_today()}",
            start=_today(),
            due=_today(),
            owner=name,
            priority="高",
            category="日常工作",
            description=result.text[:2000],
        ),
    }


# ---------------------------------------------------------------------------
# 项目结项总结 + 知识沉淀
# ---------------------------------------------------------------------------
def build_project_closure(
    project: str,
    owner: str,
    overview: str,
    results_raw: str,
    issues_raw: str = "",
    lessons_raw: str = "",
) -> dict:
    prompt = (
        "你是 V-FLO 项目结项专家。生成结项总结与知识沉淀包（对齐简道云项目结项与知识库字段）。\n"
        f"项目：{project}\n负责人：{owner}\n"
        f"项目概述：{overview}\n"
        f"成果与数据：{results_raw}\n"
        f"问题与偏差：{issues_raw or '无'}\n"
        f"经验教训：{lessons_raw or '无'}\n\n"
        "输出四部分：\n"
        "【结项总结】目标达成对照（计划 vs 实际）、关键成果、偏差与原因、成本与质量回顾。\n"
        "【知识条目】可入库的 3–5 条经验（标题|适用范围|规则|案例摘要）。\n"
        "【流程改进建议】可进入“流程改进项目”的 2–3 条。\n"
        "【后续行动】遗留事项与责任人。\n"
        "要求：数据准确、经验可复用、改进可立项。"
    )
    result = gateway.chat(
        [{"role": "system", "content": "你是项目结项与知识管理专家。"},
         {"role": "user", "content": prompt}],
        model="kimi",
        temperature=0.3,
    )
    knowledge_text = _extract_section(result.text, "知识条目")
    return {
        "type": "project_closure",
        "date": _today(),
        "title": f"项目结项 {project}",
        "content": result.text,
        "wecom_card": _extract_section(result.text, "结项总结"),
        "jdy_payload": build_jdy_task(
            title=f"【结项】{project}",
            start=_today(),
            due=_today(),
            owner=owner,
            priority="最高",
            category="项目结项",
            project=project,
            description=result.text[:2000],
        ),
        "knowledge_payload": build_jdy_knowledge(
            title=f"【结项知识】{project}",
            content=knowledge_text or result.text[:2000],
            tags=["项目结项", "知识沉淀"],
        ),
        "improvement_hints": _extract_section(result.text, "流程改进建议"),
    }


def push_to_jdy(payload: dict, kind: str = "task") -> dict:
    if kind == "knowledge":
        r = jdy.push_knowledge(payload)
    else:
        r = jdy.push_task(payload)
    return {"ok": r.ok, "mode": r.mode, "entry_id": r.entry_id, "message": r.message}


def _extract_section(text: str, header: str) -> str:
    """从生成文本中抽出某一节（兼容【X】或 **X** 标记）。"""
    import re
    if not text:
        return ""
    m = re.search(rf"[【\[]\s*{re.escape(header)}\s*[】\]]", text)
    if not m:
        m = re.search(rf"{re.escape(header)}", text)
        if not m:
            return text[:800]
    start = m.end()
    m2 = re.search(r"[【\[][^】\]]{1,20}[】\]]", text[start:])
    end = start + m2.start() if m2 else min(len(text), start + 1200)
    return text[start:end].strip(" \n：:")
