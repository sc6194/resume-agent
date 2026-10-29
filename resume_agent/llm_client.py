"""大模型客户端：兼容豆包（火山方舟）、OpenAI、DeepSeek 等 OpenAI 兼容接口。

统一走 /chat/completions，用 requests 直连，无额外依赖。
服务商选择与 Key 管理在「设置」页完成，本类只负责调用。
"""
from __future__ import annotations

import json
import re

import requests

DEFAULT_TIMEOUT = 60


class LLMError(Exception):
    """大模型 API 调用错误，message 面向用户可读。"""


class LLMClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise LLMError("未配置大模型 API Key，请先到「设置」页选择服务商并填写 Key")
        self.api_key = api_key.strip()
        self.base_url = (base_url or "").strip().rstrip("/")
        if not self.base_url:
            raise LLMError("未配置模型接口地址，请到「设置」页检查")
        self.model = (model or "").strip()
        if not self.model:
            raise LLMError("未配置模型 ID，请到「设置」页填写")

    def chat(self, messages: list, temperature: float = 0.2, max_tokens: int = 4000) -> str:
        """普通文本对话，返回模型回复正文。"""
        url = self.base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)
        except requests.exceptions.Timeout:
            raise LLMError("请求模型 API 超时，请检查网络后重试")
        except requests.exceptions.ConnectionError:
            raise LLMError("无法连接模型 API，请检查网络（是否需要代理）或接口地址后重试")

        if resp.status_code == 401:
            raise LLMError("API Key 无效或已失效，请在服务商控制台核对后到「设置」页更新")
        if resp.status_code == 404:
            raise LLMError("模型 ID 不存在或未开通，请在服务商控制台确认模型 ID 后到「设置」页更新")
        if resp.status_code == 429:
            raise LLMError("请求过于频繁（限流），请稍等片刻再试")
        if resp.status_code != 200:
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except Exception:
                detail = resp.text[:200]
            raise LLMError(f"模型 API 返回错误（{resp.status_code}）：{detail}")

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError):
            raise LLMError("模型 API 返回内容格式异常，请重试")

    def chat_json(self, messages: list, temperature: float = 0.1, max_tokens: int = 4000) -> dict:
        """要求模型输出 JSON，并解析为 dict。自动剥离 ```json 包裹。"""
        text = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
        return parse_json(text)


def parse_json(text: str) -> dict:
    """从模型回复中解析 JSON：支持裸 JSON、markdown 代码块包裹。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个 { 到最后一个 }
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise LLMError("模型未返回合法 JSON，请重试或更换模型")
