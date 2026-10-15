# -*- coding: utf-8 -*-
"""简道云（JianDaoYun）适配层。

两全其美原则（附件5 §8.1 三层分工）：
- 企业微信 = 交互与沟通层（员工习惯的地方；短版文案由员工复制发送）
- 简道云 = 制度账本 / KPI 数据源（必须留痕的地方）
- 本适配器 = 桥：把结构化结果写入简道云

接口口径（依据《简道云开放平台API接口清单》）：
- 新建：POST /api/v5/app/entry/data/create（app_id/entry_id/data 在 body；
  data 的键为字段 widget ID，值为 {"value": ...} 结构）
- 修改：POST /api/v5/app/entry/data/update（同上 + data_id）
- 查询：POST /api/v5/app/entry/data/list（data_id 游标分页）
生产：配置 JDY_APP_ID / JDY_API_KEY 后走真实接口；未配置自动 MOCK（返回模拟回执）。
生成与推送记录由调用方落库（briefings 表），本层不持久化。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import httpx

from ..config import get_settings


@dataclass
class PushResult:
    ok: bool
    mode: str  # mock / live
    entry_id: str = ""
    message: str = ""
    raw: dict = field(default_factory=dict)


class JDYClient:
    """简道云数据接口客户端（表单/流程）。"""

    def __init__(self) -> None:
        s = get_settings()
        self.app_id = getattr(s, "jdy_app_id", "") or ""
        self.api_key = getattr(s, "jdy_api_key", "") or ""
        self.entry_id_task = getattr(s, "jdy_entry_task", "") or ""       # 任务管理表单
        self.entry_id_knowledge = getattr(s, "jdy_entry_knowledge", "") or ""  # 知识库
        self.base = getattr(s, "jdy_base_url", "") or "https://api.jiandaoyun.com/api/v1"
        self.mock = not (self.app_id and self.api_key)
        # 最近一次 query_form 是否因 max_pages 截断（调用方据此决定是否允许 prune）
        self.last_truncated = False

    def push_form(self, entry_id: str, data: dict, note: str = "") -> PushResult:
        """新建一条简道云表单数据（v5 data/create，widget ID + {value} 结构）。"""
        payload = to_widget_payload(data)
        if self.mock or not entry_id:
            return PushResult(
                ok=True,
                mode="mock",
                entry_id=f"MOCK-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                message=f"[MOCK] 已模拟写入简道云 entry={entry_id or 'default'} {note}",
                raw={"data": payload},
            )
        url = self._v5_url("/app/entry/data/create")
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"app_id": self.app_id, "entry_id": entry_id, "data": payload},
                )
                resp.raise_for_status()
                obj = resp.json()
            data_obj = obj.get("data") or {}
            return PushResult(ok=True, mode="live",
                              entry_id=str(data_obj.get("_id", "")), raw=obj)
        except Exception as e:  # noqa: BLE001
            return PushResult(ok=False, mode="live", message=str(e))

    def push_task(self, data: dict, note: str = "") -> PushResult:
        return self.push_form(self.entry_id_task, data, note=note or "任务")

    def push_knowledge(self, data: dict, note: str = "") -> PushResult:
        return self.push_form(self.entry_id_knowledge, data, note=note or "知识库")

    # ---------- v5 数据接口（见《简道云开放平台API接口清单》数据接口） ----------
    def _v5_url(self, path: str) -> str:
        return self.base.replace("/api/v1", "/api/v5").rstrip("/") + path

    def query_form(
        self,
        entry_id: str,
        fields: list | None = None,
        filter: dict | None = None,  # noqa: A002 - 简道云参数名
        limit: int = 100,
        max_pages: int = 5,
    ) -> list[dict]:
        """查询多条数据（POST /api/v5/app/entry/data/list，data_id 作分页符）。

        mock 或未配置 entry 时返回空列表；分页上限 max_pages×limit，防失控拉取。
        达到上限且末页仍满 → self.last_truncated=True（同步方据此跳过 prune）。
        """
        self.last_truncated = False
        if self.mock or not entry_id:
            return []
        url = self._v5_url("/app/entry/data/list")
        out: list[dict] = []
        page_cursor = ""
        with httpx.Client(timeout=30) as client:
            for _ in range(max_pages):
                body: dict = {"app_id": self.app_id, "entry_id": entry_id, "limit": limit}
                if page_cursor:
                    body["data_id"] = page_cursor
                if fields:
                    body["fields"] = fields
                if filter:
                    body["filter"] = filter
                resp = client.post(url, headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
                resp.raise_for_status()
                rows = (resp.json() or {}).get("data") or []
                out.extend(rows)
                if len(rows) < limit:
                    break
                page_cursor = str(rows[-1].get("_id") or "")
                if not page_cursor:
                    break
            else:
                # 循环跑满 max_pages 未自然结束 → 数据被截断
                self.last_truncated = True
        return out

    def list_widgets(self, entry_id: str) -> dict[str, str]:
        """拉取表单字段配置（POST /api/v5/app/entry/widget/list）→ {widget_id: 字段中文名}。

        响应结构：{"widgets": [{"name": widget_id, "label": 中文名, ...}], "sysWidgets": [...]}
        （根级直出，无 data 包裹层）。sysWidgets 映射为中文系统字段名。
        mock/失败返回空字典（展示层回退到静态映射与 widget id）。
        """
        if self.mock or not entry_id:
            return {}
        url = self._v5_url("/app/entry/widget/list")
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"app_id": self.app_id, "entry_id": entry_id},
                )
                resp.raise_for_status()
                obj = resp.json() or {}
        except Exception:  # noqa: BLE001 — 标签获取失败不阻断数据同步
            return {}
        out: dict[str, str] = {}
        for w in obj.get("widgets") or []:
            if not isinstance(w, dict):
                continue
            wid = w.get("name") or w.get("widgetName") or ""
            label = w.get("label") or ""
            if wid and label:
                out[str(wid)] = str(label)
        sys_labels = {"creator": "创建人", "updater": "更新人", "deleter": "删除人",
                      "createTime": "创建时间", "updateTime": "更新时间", "deleteTime": "删除时间"}
        for w in obj.get("sysWidgets") or []:
            name = w.get("name") if isinstance(w, dict) else str(w)
            if name in sys_labels:
                out[name] = sys_labels[name]
        return out

    def update_form(self, entry_id: str, data_id: str, data: dict) -> PushResult:
        """修改单条数据（POST /api/v5/app/entry/data/update）。

        data 的键可为字段中文名或 widget ID；值统一包装为 {"value": ...}。
        """
        payload = to_widget_payload(data)
        if self.mock or not entry_id or not data_id:
            return PushResult(ok=True, mode="mock", entry_id=data_id,
                              message=f"[MOCK] 已模拟更新 entry={entry_id} data={data_id}",
                              raw={"data": payload})
        url = self._v5_url("/app/entry/data/update")
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"app_id": self.app_id, "entry_id": entry_id,
                          "data_id": data_id, "data": payload},
                )
                resp.raise_for_status()
            return PushResult(ok=True, mode="live", entry_id=data_id, raw=resp.json())
        except Exception as e:  # noqa: BLE001
            return PushResult(ok=False, mode="live", message=str(e))

    def upload_file(self, entry_id: str, filename: str, content: bytes,
                    mime: str = "") -> PushResult:
        """上传附件文件到简道云（POST /api/v5/app/entry/data/file/upload，multipart）。

        成功时 entry_id 字段携带 fileToken，创建数据时附件控件值用
        [{"fileToken": ..., "name": 文件名}]。APIKey 未开通文件权限时接口返回
        401/403 —— 本方法返回 ok=False，由调用方降级（如把附件名写入备注）。
        """
        if self.mock or not entry_id:
            return PushResult(ok=True, mode="mock",
                              entry_id=f"MOCK-FILE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                              message=f"[MOCK] 已模拟上传附件 {filename}",
                              raw={"name": filename})
        url = self._v5_url("/app/entry/data/file/upload")
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data={"app_id": self.app_id, "entry_id": entry_id},
                    files={"file": (filename, content, mime or "application/octet-stream")},
                )
            if resp.status_code in (401, 403):
                return PushResult(ok=False, mode="live",
                                  message="APIKey 无文件上传权限（HTTP %s），"
                                          "请在简道云开放平台为该 APIKey 开通文件上传" % resp.status_code)
            resp.raise_for_status()
            obj = resp.json() or {}
            data = obj.get("data") or {}
            token = str(data.get("fileToken") or data.get("file_token") or "")
            return PushResult(ok=bool(token), mode="live", entry_id=token, raw=obj,
                              message="" if token else f"上传响应缺少 fileToken：{obj}")
        except Exception as e:  # noqa: BLE001
            return PushResult(ok=False, mode="live", message=str(e))

    def list_departments(self) -> dict[str, int]:
        """通讯录部门 名称 → dept_no（POST /api/v5/corp/department/list）。

        知识库「部门」控件仅接受 dept_no 数字；本方法供写入前把部门名解析为编号。
        mock/失败返回空字典（调用方降级：部门字段跳过，名称并入备注）。
        """
        if self.mock:
            return {}
        url = self._v5_url("/corp/department/list")
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(url, headers={"Authorization": f"Bearer {self.api_key}"}, json={})
                resp.raise_for_status()
                obj = resp.json() or {}
        except Exception:  # noqa: BLE001 — 部门解析失败不阻断主流程
            return {}
        out: dict[str, int] = {}
        for d in obj.get("departments") or []:
            name = str(d.get("name") or "").strip()
            no = d.get("dept_no")
            if name and isinstance(no, int):
                out[name] = no
        return out

    def count_form(self, entry_id: str, filter: dict | None = None,  # noqa: A002
                   limit: int = 100, max_pages: int = 20) -> int:
        """统计数据条数（T18 KPI 取数的基础）。"""
        return len(self.query_form(entry_id, filter=filter, limit=limit, max_pages=max_pages))


jdy = JDYClient()


def build_filter(conditions: dict, rel: str = "and") -> dict:
    """构建简道云 v5 filter 结构（移植自 v-crm jdy_client，对齐官方文档）。

    conditions: {field_widget_id: (type, method)} 或 {field_widget_id: (type, method, value)}；
    rel: "and" / "or"。例：{"_widget_x": ("text", "like", "泵站")}
    """
    if rel not in ("and", "or"):
        raise ValueError(f"filter rel 只能是 and/or: {rel!r}")
    conds: list[dict] = []
    for field, spec in (conditions or {}).items():
        if len(spec) == 2:
            ftype, method = spec
            value = None
        elif len(spec) == 3:
            ftype, method, value = spec
        else:
            raise ValueError(f"非法 filter 条件 {field}: {spec!r}")
        cond: dict = {"field": field, "type": ftype, "method": method}
        if value is not None:
            cond["value"] = value
        conds.append(cond)
    return {"rel": rel, "cond": conds}


# ---------------------------------------------------------------------------
# 字段名 → widget ID 映射（依据《简道云各模块详细接口字段信息汇总表》「项目执行->任务管理」）
# v5 数据接口要求：data = {"<widget_id>": {"value": ...}}
# ---------------------------------------------------------------------------
# 与 task_agent.JDY_FIELD_MAP 同源核对（已对照字段汇总表逐字段验证）
TASK_LABEL_TO_WIDGET = {
    "任务名称": "_widget_1668082756215",
    "任务编号": "_widget_1710402153871",
    "项目编号": "_widget_1669429084883",
    "项目名称": "_widget_1710399012344",   # 所属项目为关联字段(json)，文本写入用项目名称
    "所属项目": "_widget_1710399012344",
    "主负责人": "_widget_1668085072209",
    "负责人": "_widget_1749021035267",     # array
    "协作人": "_widget_1749021035267",     # 并入负责人数组
    "负责部门": "_widget_1749021035268",
    "任务状态": "_widget_1668690637187",
    "开始时间": "_widget_1667894235099",
    "截止时间": "_widget_1667894235119",
    "预计工时（小时）": "_widget_1710399012345",
    "优先级": "_widget_1668689007999",
    "添加附件": "_widget_1668085072214",
    "任务描述": "_widget_1668085072208",
    "任务一级分类": "_widget_1749085291625",
    "一级任务分类": "_widget_1749085291625",
    "任务二级分类": "_widget_1749085291627",
    "二级任务分类": "_widget_1749085291627",
    "任务属性": "_widget_1710399012342",
    "所属项目阶段": "_widget_1710401489891",
    "WBS 编号": "_widget_1710491067381",
}

# 日期/时间字段：v5 要求 ISO 格式
_DATE_WIDGETS = {"_widget_1667894235099", "_widget_1667894235119"}

# ---------------------------------------------------------------------------
# 知识库表单字段映射（已对线上表单 68ad15ab88c411d76390e0a2 的 widget/list 实测核对）
# 表单字段：客户/项目/问题/回答/附件/备注/国家/部门（部门为 dept 控件，仅接受 dept_no 数字）
# ---------------------------------------------------------------------------
KNOWLEDGE_LABEL_TO_WIDGET = {
    "客户": "_widget_1756173740163",
    "项目": "_widget_1756173740164",
    "问题": "_widget_1756173740165",
    "回答": "_widget_1768902936664",
    "附件": "_widget_1767494919162",
    "备注": "_widget_1756173740167",
    "国家": "_widget_1756173740168",
    "部门": "_widget_1756196363918",
}

# 合并映射（两表字段标签无重名冲突，已逐一核对）
LABEL_TO_WIDGET: dict[str, str] = {**TASK_LABEL_TO_WIDGET, **KNOWLEDGE_LABEL_TO_WIDGET}

# 附件控件（upload 类型只接受文件对象结构 list[dict]）
_ATTACH_WIDGETS = {"_widget_1668085072214", KNOWLEDGE_LABEL_TO_WIDGET["附件"]}
# 部门控件（dept 类型只接受 dept_no 数字；名称须先经 list_departments 解析）
_DEPT_WIDGETS = {KNOWLEDGE_LABEL_TO_WIDGET["部门"]}

# widget → 中文标签静态兜底（任务管理表 + 知识库表；list_widgets 失败/未配置时镜像展示仍友好）
WIDGET_LABEL_FALLBACK: dict[str, str] = {v: k for k, v in LABEL_TO_WIDGET.items()}


def _to_iso_date(v):
    s = str(v or "").strip()
    if not s:
        return ""
    if "T" in s:
        return s
    if len(s) == 10 and s[4] == "-":
        return f"{s}T00:00:00.000Z"
    return s


def to_widget_payload(data: dict) -> dict:
    """把「中文字段名: 值」字典转成 v5 需要的 {widget_id: {value: ...}}。

    - 已是 _widget_ 开头的键直接包装；
    - 未识别的字段名丢弃（由调用方保证字段在映射表内）；
    - 附件字段仅在值为合法结构（list[dict]）时透传，否则跳过（避免 live 模式报错）；
    - 部门控件仅接受 dept_no 数字（名称须先由 list_departments 解析），其余跳过。
    """
    out: dict = {}
    for k, v in (data or {}).items():
        widget = k if str(k).startswith("_widget_") else LABEL_TO_WIDGET.get(str(k))
        if not widget:
            continue
        if widget in _ATTACH_WIDGETS and not (isinstance(v, list) and (not v or isinstance(v[0], dict))):
            continue  # 附件只接受文件对象结构
        if widget in _DEPT_WIDGETS:
            if isinstance(v, str) and v.strip().isdigit():
                v = int(v.strip())
            elif isinstance(v, bool) or not isinstance(v, (int, float, list)):
                continue  # 未解析的部门名不写入（避免 live 校验报错）
            if isinstance(v, list) and not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
                continue
        if widget in _DATE_WIDGETS:
            v = _to_iso_date(v)
            if not v:
                continue
        if widget in out and isinstance(out[widget].get("value"), list) and isinstance(v, list):
            out[widget]["value"] = out[widget]["value"] + v  # 负责人+协作人合并
            continue
        out[widget] = v if (isinstance(v, dict) and "value" in v) else {"value": v}
    return out


# ---------------------------------------------------------------------------
# 简道云任务五要素模板（对齐 KPI 数据采集字段）
# ---------------------------------------------------------------------------
def build_jdy_task(
    title: str,
    start: str,
    due: str,
    owner: str,
    priority: str = "较高",
    project: str = "",
    category: str = "日常工作",
    description: str = "",
    attachments: Optional[list] = None,
    collaborators: Optional[list] = None,
    extra: Optional[dict] = None,
) -> dict:
    """构造简道云「任务管理」字段（字段名以实际表单为准，可配置映射）。"""
    payload = {
        "任务名称": title,
        "开始时间": start,
        "截止时间": due,
        "负责人": [owner] if isinstance(owner, str) else owner,
        "优先级": priority,
        "所属项目": project,
        "任务一级分类": category,
        "任务描述": description,
        "协作人": collaborators or [],
        "添加附件": attachments or [],
    }
    if extra:
        payload.update(extra)
    return payload


def build_jdy_knowledge(
    question: str,
    answer: str,
    customer: str = "",
    project: str = "",
    country: str = "",
    remark: str = "",
    dept: str | int | None = "",
    attachments: Optional[list] = None,
) -> dict:
    """构造知识库表单 payload（字段已对线上表单 68ad15ab88c411d76390e0a2 核对）。

    - question/answer 为必填主体（问题/回答）；
    - dept 传部门名称时仅作记录，真正写入需先经 list_departments 解析为 dept_no；
    - attachments 为 [{"fileToken": ..., "name": ...}] 结构（由 upload_file 取得）。
    """
    return {
        "问题": question,
        "回答": answer,
        "客户": customer,
        "项目": project,
        "国家": country,
        "备注": remark,
        "部门": dept or "",
        "附件": attachments or [],
    }
