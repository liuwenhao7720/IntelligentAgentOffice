# -*- coding: utf-8 -*-
"""智能对话模块 · 上传文件文本解析。

支持：txt/md/csv/log/json（直接读取，utf-8 失败回退 gbk）、docx、xlsx、pdf。
解析结果三元组：(text, status, note)
- status=ok          正常解析（可能经过截断，由调用方截断，这里返回全文）
- status=failed      解析失败或无可提取文本（如扫描件 PDF），note 说明原因
- status=unsupported 不支持的类型（路由层通常已按白名单拦截，此处兜底）

解析库（pypdf / python-docx / openpyxl）为惰性导入：缺失时返回 failed 而不是
让模块导入失败，保证其余功能可用（部署清单已将三者打入离线安装包）。
"""
from __future__ import annotations

from pathlib import Path

# 允许上传的扩展名（小写、不含点）
ALLOWED_EXTS = {"txt", "md", "csv", "log", "json", "docx", "xlsx", "pdf"}
# 按纯文本直接读取的类型
TEXT_EXTS = {"txt", "md", "csv", "log", "json"}

# 解析保护上限（防内存/耗时失控）
PDF_MAX_PAGES = 50
XLSX_MAX_ROWS_PER_SHEET = 200
XLSX_MAX_SHEETS = 20


def safe_ext(filename: str) -> str:
    """取小写扩展名（不含点）；无扩展名返回空串。"""
    return Path(filename or "").suffix.lower().lstrip(".")


def is_allowed(ext: str) -> bool:
    return ext in ALLOWED_EXTS


def extract_text(path: str | Path, ext: str) -> tuple[str, str, str]:
    """解析文件为纯文本。任何异常都收敛为 (\"\", \"failed\", note)，不向调用方抛出。"""
    ext = (ext or "").lower()
    try:
        if ext in TEXT_EXTS:
            return _extract_text_plain(path)
        if ext == "docx":
            return _extract_docx(path)
        if ext == "xlsx":
            return _extract_xlsx(path)
        if ext == "pdf":
            return _extract_pdf(path)
        return "", "unsupported", f"不支持的文件类型：.{ext}"
    except Exception as e:  # noqa: BLE001 — 解析第三方格式必须兜底，不让单个坏文件 500
        return "", "failed", f"解析失败：{type(e).__name__}"


def _extract_text_plain(path: str | Path) -> tuple[str, str, str]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    text = text.strip()
    if not text:
        return "", "failed", "文件为空"
    return text, "ok", ""


def _extract_docx(path: str | Path) -> tuple[str, str, str]:
    try:
        import docx
    except ImportError:
        return "", "failed", "服务端缺少 python-docx 依赖，无法解析 Word 文档"
    doc = docx.Document(str(path))
    parts: list[str] = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            line = " | ".join(c for c in cells if c)
            if line:
                parts.append(line)
    text = "\n".join(parts).strip()
    if not text:
        return "", "failed", "未能解析出文本（文档可能为空或全为图片）"
    return text, "ok", ""


def _extract_xlsx(path: str | Path) -> tuple[str, str, str]:
    try:
        import openpyxl
    except ImportError:
        return "", "failed", "服务端缺少 openpyxl 依赖，无法解析 Excel 文件"
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    parts: list[str] = []
    truncated = False
    for sheet in wb.worksheets[:XLSX_MAX_SHEETS]:
        parts.append(f"### 工作表：{sheet.title}")
        for i, row in enumerate(sheet.iter_rows(values_only=True)):
            if i >= XLSX_MAX_ROWS_PER_SHEET:
                parts.append(f"（该工作表仅截取前 {XLSX_MAX_ROWS_PER_SHEET} 行）")
                truncated = True
                break
            cells = ["" if c is None else str(c) for c in row]
            line = " | ".join(cells).rstrip(" |")
            if line.strip():
                parts.append(line)
    wb.close()
    text = "\n".join(parts).strip()
    if not text:
        return "", "failed", "未能解析出文本（工作表可能为空）"
    return text, "ok", ("内容较长已截断" if truncated else "")


def _extract_pdf(path: str | Path) -> tuple[str, str, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "failed", "服务端缺少 pypdf 依赖，无法解析 PDF"
    reader = PdfReader(str(path))
    parts: list[str] = []
    pages = len(reader.pages)
    for page in reader.pages[:PDF_MAX_PAGES]:
        try:
            t = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001 — 单页失败不拖垮整份文件
            continue
        if t:
            parts.append(t)
    text = "\n\n".join(parts).strip()
    note = ""
    if pages > PDF_MAX_PAGES:
        note = f"共 {pages} 页，仅解析前 {PDF_MAX_PAGES} 页"
    if not text:
        return "", "failed", "未能解析出文本（可能是扫描件或加密 PDF）"
    return text, "ok", note
