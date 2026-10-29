"""开源项目搜索：GitHub + Gitee 双平台。

- GitHub：REST /search/repositories，可选 Token（匿名限额 60次/小时）
- Gitee：v5 /search/repositories，可选 Token（匿名也可搜）
搜索失败/网络不通时自动切换平台，并把结果归一化为项目库同构数据。
"""
from __future__ import annotations

import requests

TIMEOUT = 12

GITHUB_API = "https://api.github.com"
GITEE_API = "https://gitee.com/api/v5"


class OSSError(Exception):
    pass


def search_github(query: str, token: str = "", per_page: int = 12) -> list:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "resume-agent"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    try:
        resp = requests.get(GITHUB_API + "/search/repositories",
                            headers=headers, params=params, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise OSSError(f"GitHub 连接失败：{e}")

    if resp.status_code == 401:
        raise OSSError("GitHub Token 无效，请到「设置」页更新；或清空 Token 用匿名搜索")
    if resp.status_code == 403:
        raise OSSError("GitHub 搜索达到速率限制（匿名 60次/小时）。建议在「设置」页填 GitHub Token 提升额度")
    if resp.status_code == 422:
        raise OSSError("GitHub 搜索词不合法，请调整关键词")
    if resp.status_code != 200:
        raise OSSError(f"GitHub 搜索失败（{resp.status_code}）")

    items = resp.json().get("items", [])
    result = []
    for it in items:
        result.append({
            "full_name": it.get("full_name", ""),
            "html_url": it.get("html_url", ""),
            "description": (it.get("description") or "")[:300],
            "stars": it.get("stargazers_count") or 0,
            "language": it.get("language") or "",
            "topics": (it.get("topics") or [])[:8],
            "platform": "github",
        })
    return result


def search_gitee(query: str, token: str = "", per_page: int = 12) -> list:
    params = {
        "q": query,
        "sort": "stars_count",
        "order": "desc",
        "per_page": per_page,
    }
    if token:
        params["access_token"] = token
    try:
        resp = requests.get(GITEE_API + "/search/repositories",
                            params=params, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise OSSError(f"Gitee 连接失败：{e}")

    if resp.status_code == 401:
        raise OSSError("Gitee Token 无效，请到「设置」页更新；或清空 Token 用匿名搜索")
    if resp.status_code == 403:
        raise OSSError("Gitee 搜索达到速率限制，请稍后再试或填 Gitee Token")
    if resp.status_code != 200:
        raise OSSError(f"Gitee 搜索失败（{resp.status_code}）")

    items = resp.json()
    if not isinstance(items, list):
        raise OSSError("Gitee 返回格式异常")

    result = []
    for it in items:
        result.append({
            "full_name": it.get("full_name", ""),
            "html_url": it.get("html_url", ""),
            "description": (it.get("description") or "")[:300],
            "stars": it.get("stargazers_count") or 0,
            "language": it.get("language") or "",
            "topics": [],
            "platform": "gitee",
        })
    return result


GENERIC_SKILLS = {"python", "java", "javascript", "c", "c++", "c#", "go", "php", "ruby", "前端", "后端", "全栈"}


def build_query(analysis: dict, manual: str = "") -> str:
    """构造搜索词（适度原则：默认只取 1-2 个核心技能词，避免条件太多搜不到）。

    manual 非空时以用户手动输入为准。
    """
    manual = (manual or "").strip()
    if manual:
        return manual
    skills = [s.get("skill", "").strip() for s in (analysis.get("key_skills") or []) if s.get("skill").strip()]
    if not skills:
        keywords = [k.strip() for k in (analysis.get("keywords") or []) if k.strip()][:2]
        return (" ".join(keywords)) or "python"
    first = skills[0]
    # 首个词是泛语言词时补第二个技能词，否则只用一个词，保证能搜到结果
    if first.lower() in GENERIC_SKILLS and len(skills) > 1:
        return f"{first} {skills[1]}"
    return first


def search_any(analysis: dict, settings: dict, manual: str = "", order=("github", "gitee")) -> dict:
    """依次尝试两个平台，返回 {platform, candidates, query, errors}。

    order 决定优先平台，某个平台失败会记录 error 并继续下一个。
    """
    query = build_query(analysis, manual)
    errors = []
    candidates = []
    used_platform = None
    for platform in order:
        try:
            if platform == "github":
                # GitHub 支持 language: 限定，帮助过滤非目标语言项目
                gh_q = query if "language:" in query else f"{query} language:python"
                hits = search_github(gh_q, token=settings.get("github_token", ""))
            else:
                hits = search_gitee(query, token=settings.get("gitee_token", ""))
        except OSSError as e:
            errors.append(f"{platform}: {e}")
            continue
        candidates = hits
        used_platform = platform
        if hits:
            break
        errors.append(f"{platform}: 未搜到结果")
    return {
        "platform": used_platform,
        "query": query,
        "candidates": candidates,
        "errors": errors,
    }


def fetch_readme(full_name: str, platform: str, token: str = "") -> str:
    """抓取仓库 README 前 1500 字符，供部署指引展示；失败返回空串。"""
    try:
        if platform == "github":
            url = f"https://raw.githubusercontent.com/{full_name}/HEAD/README.md"
            headers = {"User-Agent": "resume-agent"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            url = GITEE_API + f"/repos/{full_name}/readme"
            params = {"access_token": token} if token else {}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                import base64
                try:
                    return base64.b64decode(content).decode("utf-8", errors="ignore")[:1500]
                except Exception:
                    return content[:1500]
            return ""
        if resp.status_code == 200:
            return resp.text[:1500]
    except Exception:
        pass
    return ""


def to_project(candidate: dict) -> dict:
    """把开源候选归一化为项目库数据结构（技术栈留空，由用户部署后补充）。"""
    return {
        "name": candidate.get("full_name", ""),
        "role": "开源项目部署实践",
        "tech_stack": [candidate["language"]] if candidate.get("language") else [],
        "description": candidate.get("description", "")[:200],
        "highlights": [
            f"Star {candidate.get('stars', 0)} 的开源项目",
            "已实际部署并验证可运行" if False else "完成本地部署与环境配置",
        ],
        "source": candidate.get("platform", "github"),
        "source_url": candidate.get("html_url", ""),
    }
