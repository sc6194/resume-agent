"""数据层：设置、个人资料、项目库、分析报告的 JSON 持久化。

所有数据存放在项目根目录的 data/ 文件夹下，纯 JSON，无数据库依赖。
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

# data/ 目录固定在项目根（本文件上一级）
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TEMPLATE_DIR = os.path.join(DATA_DIR, "templates")
RESUME_DIR = os.path.join(DATA_DIR, "resumes")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
PROFILE_FILE = os.path.join(DATA_DIR, "profile.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
ANALYSIS_FILE = os.path.join(DATA_DIR, "cache", "last_analysis.json")
REPORT_FILE = os.path.join(DATA_DIR, "cache", "last_report.json")
OSS_CACHE_FILE = os.path.join(DATA_DIR, "cache", "oss_candidates.json")


def _ensure_dirs() -> None:
    for d in (DATA_DIR, TEMPLATE_DIR, RESUME_DIR, CACHE_DIR):
        os.makedirs(d, exist_ok=True)


def load_json(path: str, default: object) -> object:
    """读取 JSON 文件，不存在或损坏时返回 default。"""
    _ensure_dirs()
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: str, data: object) -> None:
    _ensure_dirs()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------- 设置 ----------------

# 大模型服务商预设（接口地址 / 推荐模型）
PROVIDER_PRESETS = {
    "doubao": {
        "label": "豆包（火山方舟）",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-1.6-flash",
        "key_hint": "在 console.volcengine.com/ark 创建 API Key",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_hint": "在 platform.openai.com 创建 API Key",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_hint": "在 platform.deepseek.com 创建 API Key",
    },
    "custom": {
        "label": "自定义（OpenAI 兼容）",
        "base_url": "",
        "model": "",
        "key_hint": "任意 OpenAI 兼容接口：第三方中转站、本地 Ollama 等，接口地址和模型 ID 自行填写",
    },
}

DEFAULT_SETTINGS = {
    "llm_provider": "doubao",  # doubao | openai | deepseek | custom
    "doubao_api_key": "",
    "doubao_base_url": PROVIDER_PRESETS["doubao"]["base_url"],
    "doubao_model": PROVIDER_PRESETS["doubao"]["model"],
    "openai_api_key": "",
    "openai_base_url": PROVIDER_PRESETS["openai"]["base_url"],
    "openai_model": PROVIDER_PRESETS["openai"]["model"],
    "deepseek_api_key": "",
    "deepseek_base_url": PROVIDER_PRESETS["deepseek"]["base_url"],
    "deepseek_model": PROVIDER_PRESETS["deepseek"]["model"],
    "custom_api_key": "",
    "custom_base_url": "",
    "custom_model": "",
    "github_token": "",
    "gitee_token": "",
}


def load_settings() -> dict:
    data = load_json(SETTINGS_FILE, {}) or {}
    # 迁移旧版字段（此前只有豆包一项，字段名带 ark_ 前缀）
    if "ark_api_key" in data and not data.get("doubao_api_key"):
        data["doubao_api_key"] = data.pop("ark_api_key", "")
    if "ark_base_url" in data and not data.get("doubao_base_url"):
        data["doubao_base_url"] = data.pop("ark_base_url", "")
    if "ark_model" in data and not data.get("doubao_model"):
        data["doubao_model"] = data.pop("ark_model", "")
    if "llm_provider" not in data:
        data["llm_provider"] = "doubao"
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    return merged


def save_settings(settings: dict) -> None:
    save_json(SETTINGS_FILE, settings)


def get_llm_config(settings: dict | None = None) -> dict:
    """按当前服务商返回 {api_key, base_url, model}，缺省值回退到预设。"""
    s = settings or load_settings()
    provider = s.get("llm_provider") or "doubao"
    if provider not in PROVIDER_PRESETS:
        provider = "doubao"
    preset = PROVIDER_PRESETS[provider]
    return {
        "provider": provider,
        "api_key": (s.get(f"{provider}_api_key") or "").strip(),
        "base_url": (s.get(f"{provider}_base_url") or "").strip() or preset["base_url"],
        "model": (s.get(f"{provider}_model") or "").strip() or preset["model"],
    }


# ---------------- 个人资料 ----------------

EMPTY_PROFILE = {
    "name": "",
    "phone": "",
    "email": "",
    "city": "",
    "school": "",
    "major": "",
    "degree": "",
    "graduation": "",
    "target_position": "",
    "summary": "",
    "skills": "",
    "experience": "",
    "certificates": "",
    "languages": "",
}


def load_profile() -> dict:
    data = load_json(PROFILE_FILE, {})
    merged = dict(EMPTY_PROFILE)
    merged.update(data or {})
    return merged


def save_profile(profile: dict) -> None:
    # 只保留已知字段，防止脏数据
    clean = {k: (profile.get(k) or "") for k in EMPTY_PROFILE}
    save_json(PROFILE_FILE, clean)


# ---------------- 项目库 ----------------

def list_projects() -> list:
    return load_json(PROJECTS_FILE, [])


def get_project(project_id: str) -> dict | None:
    for p in list_projects():
        if p.get("id") == project_id:
            return p
    return None


def add_project(project: dict) -> dict:
    projects = list_projects()
    project.setdefault("id", uuid.uuid4().hex)
    project.setdefault("created_at", datetime.now().strftime("%Y-%m-%d %H:%M"))
    project.setdefault("deployed", False)
    project.setdefault("deploy_url", "")
    project.setdefault("deploy_date", "")
    project.setdefault("source", "user")  # user | github | gitee
    project.setdefault("source_url", "")
    project.setdefault("highlights", [])
    if isinstance(project.get("highlights"), str):
        project["highlights"] = [h.strip() for h in project["highlights"].split("\n") if h.strip()]
    projects.append(project)
    save_json(PROJECTS_FILE, projects)
    return project


def update_project(project_id: str, patch: dict) -> dict | None:
    projects = list_projects()
    for p in projects:
        if p.get("id") == project_id:
            for k, v in patch.items():
                p[k] = v
            save_json(PROJECTS_FILE, projects)
            return p
    return None


def delete_project(project_id: str) -> bool:
    projects = list_projects()
    remain = [p for p in projects if p.get("id") != project_id]
    if len(remain) == len(projects):
        return False
    save_json(PROJECTS_FILE, remain)
    return True


def mark_deployed(project_id: str, deploy_url: str) -> dict | None:
    return update_project(project_id, {
        "deployed": True,
        "deploy_url": deploy_url,
        "deploy_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


# ---------------- 分析报告 / 开源候选缓存 ----------------

def save_analysis(analysis: dict) -> None:
    save_json(ANALYSIS_FILE, analysis)


def load_analysis() -> dict | None:
    data = load_json(ANALYSIS_FILE, None)
    return data if data else None


def save_report(report: dict) -> None:
    save_json(REPORT_FILE, report)


def load_report() -> dict | None:
    data = load_json(REPORT_FILE, None)
    return data if data else None


def save_oss_candidates(candidates: list) -> None:
    save_json(OSS_CACHE_FILE, candidates)


def load_oss_candidates() -> list:
    return load_json(OSS_CACHE_FILE, [])


# ---------------- 岗位分析历史 ----------------

HISTORY_FILE = os.path.join(DATA_DIR, "cache", "history.json")


def list_history() -> list:
    return load_json(HISTORY_FILE, [])


def add_history(entry: dict) -> dict:
    history = list_history()
    entry.setdefault("id", uuid.uuid4().hex)
    entry.setdefault("time", datetime.now().strftime("%Y-%m-%d %H:%M"))
    history.insert(0, entry)  # 最新在前
    history = history[:100]  # 最多保留 100 条
    save_json(HISTORY_FILE, history)
    return entry


def get_history(history_id: str) -> dict | None:
    for h in list_history():
        if h.get("id") == history_id:
            return h
    return None


def delete_history(history_id: str) -> bool:
    history = list_history()
    remain = [h for h in history if h.get("id") != history_id]
    if len(remain) == len(history):
        return False
    save_json(HISTORY_FILE, remain)
    return True


# ---------------- 工作经历适配分析缓存 ----------------

EXPERIENCE_ANALYSIS_FILE = os.path.join(DATA_DIR, "cache", "experience_analysis.json")


def save_experience_analysis(data: dict) -> None:
    save_json(EXPERIENCE_ANALYSIS_FILE, data)


def load_experience_analysis() -> dict | None:
    data = load_json(EXPERIENCE_ANALYSIS_FILE, None)
    return data if data else None


def delete_template(filename: str) -> bool:
    """删除上传的简历模板文件。"""
    _ensure_dirs()
    name = os.path.basename(filename)
    path = os.path.join(TEMPLATE_DIR, name)
    if not os.path.exists(path) or not name.lower().endswith(".docx"):
        return False
    os.remove(path)
    return True


def delete_resume(filename: str) -> bool:
    """删除生成的简历文件。"""
    _ensure_dirs()
    name = os.path.basename(filename)
    path = os.path.join(RESUME_DIR, name)
    if not os.path.exists(path) or not name.lower().endswith(".docx"):
        return False
    os.remove(path)
    return True


def list_uploaded_templates() -> list:
    """返回 data/templates 下的 docx 模板文件名。"""
    _ensure_dirs()
    files = []
    if os.path.isdir(TEMPLATE_DIR):
        for name in os.listdir(TEMPLATE_DIR):
            if name.lower().endswith(".docx"):
                files.append(name)
    return files


def list_generated_resumes() -> list:
    _ensure_dirs()
    files = []
    if os.path.isdir(RESUME_DIR):
        for name in os.listdir(RESUME_DIR):
            if name.lower().endswith(".docx"):
                files.append(name)
    files.sort(key=lambda n: os.path.getmtime(os.path.join(RESUME_DIR, n)), reverse=True)
    return files
