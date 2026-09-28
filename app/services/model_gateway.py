# -*- coding: utf-8 -*-
"""T04 模型网关：Mimo / DeepSeek / Kimi 统一适配 + 推荐切换 + 降级 + 计量。
OpenAI 兼容接口；无密钥时 mock，便于本地验收。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator, Optional

import httpx

from ..config import get_settings

MODEL_ALIASES = {
    "mimo": "mimo",
    "deepseek": "deepseek",
    "kimi": "kimi",
}

# 场景/任务 → 推荐模型（保持愚蠢简单，可由管理端覆盖）
TASK_MODEL_MAP = {
    "write": "kimi",       # 长文写作、报告、方案
    "chat": "mimo",        # 日常、快答、邮件润色
    "code": "deepseek",    # 代码、分析、结构化
    "analysis": "deepseek",
    "translate": "kimi",
    "summary": "kimi",
}


@dataclass
class ModelResult:
    text: str
    model: str
    provider: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    degraded: bool = False
    raw: dict | None = None


class ModelGateway:
    def __init__(self) -> None:
        self.s = get_settings()
        self._mock = self.s.mock_llm or not self.s.any_model_key()

    def recommend(self, task_tag: str = "chat", scenario_default: Optional[str] = None) -> str:
        if scenario_default and scenario_default in MODEL_ALIASES:
            return scenario_default
        return TASK_MODEL_MAP.get(task_tag, "mimo")

    def _provider_config(self, name: str):
        name = MODEL_ALIASES.get(name, name)
        if name == "mimo":
            return "mimo", self.s.mimo_api_key, self.s.mimo_base_url, self.s.mimo_model
        if name == "deepseek":
            return "deepseek", self.s.deepseek_api_key, self.s.deepseek_base_url, self.s.deepseek_model
        if name == "kimi":
            return "kimi", self.s.kimi_api_key, self.s.kimi_base_url, self.s.kimi_model
        raise ValueError(f"unknown model: {name}")

    def available_models(self) -> list[dict]:
        out = []
        for name in ("mimo", "deepseek", "kimi"):
            _, key, _, model_id = self._provider_config(name)
            out.append({
                "name": name,
                "model_id": model_id,
                "available": bool(key) or self._mock,
                "mock": self._mock or not bool(key),
            })
        return out

    def chat(
        self,
        messages: list[dict],
        model: str = "mimo",
        temperature: float = 0.4,
        max_tokens: int = 2000,
    ) -> ModelResult:
        """非流式。失败自动降级到备选模型。"""
        primary = MODEL_ALIASES.get(model, "mimo")
        fallback = "kimi" if primary != "kimi" else "deepseek"
        try:
            return self._invoke(primary, messages, temperature, max_tokens)
        except Exception as e:  # noqa: BLE001 — 降级是产品行为
            if self._mock:
                raise
            try:
                r = self._invoke(fallback, messages, temperature, max_tokens)
                r.degraded = True
                return r
            except Exception:
                raise RuntimeError(f"模型调用失败: {e}") from e

    def chat_stream(
        self,
        messages: list[dict],
        model: str = "mimo",
        temperature: float = 0.4,
        max_tokens: int = 2000,
    ) -> Iterator[str]:
        """流式输出；mock 模式按段吐出。"""
        if self._mock:
            result = self._invoke(model, messages, temperature, max_tokens)
            chunk = 40
            text = result.text
            for i in range(0, len(text), chunk):
                yield text[i : i + chunk]
                time.sleep(0.02)
            return

        provider, key, base_url, model_id = self._provider_config(model)
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        with httpx.Client(timeout=self.s.request_timeout) as client:
            with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = obj.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content") or ""
                    if content:
                        yield content

    def _invoke(
        self, model: str, messages: list[dict], temperature: float, max_tokens: int
    ) -> ModelResult:
        start = time.time()
        if self._mock:
            return self._mock_result(model, messages, start)

        provider, key, base_url, model_id = self._provider_config(model)
        if not key:
            raise RuntimeError(f"{provider} 未配置 API Key")
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        with httpx.Client(timeout=self.s.request_timeout) as client:
            resp = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
            resp.raise_for_status()
            obj = resp.json()
        text = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = obj.get("usage", {}) or {}
        return ModelResult(
            text=text,
            model=model_id,
            provider=provider,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            latency_ms=int((time.time() - start) * 1000),
            raw=obj,
        )

    def _mock_result(self, model: str, messages: list[dict], start: float) -> ModelResult:
        user_text = ""
        for m in messages:
            if m.get("role") == "user":
                user_text = m.get("content", "")
        preview = user_text.strip().replace("\n", " ")
        if len(preview) > 180:
            preview = preview[:180] + "…"
        text = (
            f"【MOCK · {model}】已根据场景提示词生成初稿。\n\n"
            f"## 产出草稿\n\n"
            f"（此处为本地联调占位。配置对应模型 API Key 后将输出真实内容。）\n\n"
            f"**输入摘要**：{preview}\n\n"
            f"### 结构建议\n"
            f"1. 结论先行\n"
            f"2. 要点分条\n"
            f"3. 下一步行动（责任人 / 时间）\n\n"
            f"> 请在本页直接修改，系统将保存「AI初稿 vs 人工定稿」差异作为公司数字资产。"
        )
        return ModelResult(
            text=text,
            model=f"mock-{model}",
            provider="mock",
            tokens_in=len(preview),
            tokens_out=len(text),
            latency_ms=int((time.time() - start) * 1000),
        )


gateway = ModelGateway()
