"""岗位解析、项目匹配评分、项目描述改写、开源候选排序。

所有智能判断通过豆包模型完成，输出统一为结构化 JSON。
"""
from __future__ import annotations

from typing import Optional

from .llm_client import LLMClient, LLMError

SYSTEM_PROMPT = (
    "你是一名资深技术招聘顾问兼简历优化专家，服务一位国内应届生求职者。"
    "你只输出严格合法的 JSON，不输出任何多余文字、解释或 markdown 代码块。"
)


def analyze_job(job_text: str, client: LLMClient) -> dict:
    """解析岗位信息，输出结构化技能/职责/要求清单。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "下面是招聘方发布的岗位信息原文。请解析并输出如下结构的 JSON：\n"
            "{\n"
            '  "position": "岗位名称",\n'
            '  "company": "公司名称（原文没有则空字符串）",\n'
            '  "key_skills": [{"skill": "技能/技术关键词", "weight": 0-1的数字表示重要程度}],\n'
            '  "responsibilities": ["工作职责要点1", ...],\n'
            '  "requirements": ["任职要求要点1", ...],\n'
            '  "education_requirement": "学历要求（没有则空字符串）",\n'
            '  "salary": "薪资区间（没有则空字符串）",\n'
            '  "keywords": ["其他关键词，用于开源项目搜索，如 Django、爬虫、数据分析等"]\n'
            "}\n"
            "key_skills 至少提取 5 个，按重要程度从高到低排序；"
            "keywords 与 key_skills 不同，偏向技术栈/领域词，用于搜索开源项目。\n"
            f"===== 岗位信息原文 =====\n{job_text}"
        )},
    ]
    result = client.chat_json(messages, temperature=0.1, max_tokens=3000)
    # 兜底补全字段
    result.setdefault("position", "")
    result.setdefault("company", "")
    result.setdefault("key_skills", [])
    result.setdefault("responsibilities", [])
    result.setdefault("requirements", [])
    result.setdefault("education_requirement", "")
    result.setdefault("salary", "")
    result.setdefault("keywords", [])
    if not result.get("key_skills"):
        raise LLMError("岗位解析失败：未提取到技能关键词，请检查岗位文本是否完整")
    return result


def match_projects(analysis: dict, projects: list, client: LLMClient) -> dict:
    """把用户项目库与岗位要求逐一评分，输出匹配报告。

    projects 传 [{id, name, role, tech_stack, description, highlights}]，
    高亮点列表在传输时合并成换行文本，控制 token 消耗。
    """
    if not projects:
        return {
            "results": [],
            "best_project_id": None,
            "has_good_match": False,
            "missing_skills": [s["skill"] for s in analysis.get("key_skills", [])],
            "summary": "项目库为空，需要从开源平台寻找适配项目。",
        }

    projects_brief = []
    for p in projects:
        hl = p.get("highlights") or []
        projects_brief.append(
            f'- id="{p.get("id")}" name="{p.get("name", "")}" role="{p.get("role", "")}" '
            f'tech="{",".join(p.get("tech_stack", []))}" desc="{p.get("description", "")[:300]}" '
            f'highlights={";".join(hl[:5])[:300]} deployed={str(bool(p.get("deployed"))).lower()}'
        )
    projects_text = "\n".join(projects_brief)

    skills_text = "、".join(
        f'{s.get("skill")}(权重{s.get("weight", 0.5)})' for s in analysis.get("key_skills", [])
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "请把下面每个候选项目与目标岗位的匹配度逐一评分。\n"
            f"目标岗位：{analysis.get('position', '')}\n"
            f"核心技能要求（含权重）：{skills_text}\n"
            f"岗位职责：{'；'.join(analysis.get('responsibilities', []))}\n"
            f"任职要求：{'；'.join(analysis.get('requirements', []))}\n"
            "\n候选项目列表：\n" + projects_text +
            "\n\n输出 JSON：\n"
            "{\n"
            '  "results": [\n'
            "    {\n"
            '      "id": "项目id（原样返回）",\n'
            '      "score": 0-100整数（匹配度评分）,\n'
            '      "verdict": "high|medium|low",\n'
            '      "reason": "匹配理由，60字内，结合岗位要求说清哪里匹配",\n'
            '      "highlight_points": ["针对该岗位最值得突出的2-4个点"],\n'
            '      "gap": "与岗位的差距/短板，30字内"\n'
            "    }\n"
            "  ],\n"
            '  "best_project_id": "得分最高的项目id（得分都不超过60则填null）",\n'
            '  "has_good_match": true或false（是否存在 score>=70 的项目）,\n'
            '  "missing_skills": ["岗位要求但项目库整体缺失的技能，3-5个"],\n'
            '  "summary": "一句话总结匹配情况（40字内）"\n'
            "}\n"
            "评分标准：技术栈直接命中且职责覆盖度高为 85+；部分命中 70-84；仅沾边 55-69；"
            "基本无关 <55。verdict：score>=80 为 high，60-79 为 medium，否则 low。"
        )},
    ]
    report = client.chat_json(messages, temperature=0.1, max_tokens=4000)
    report.setdefault("results", [])
    report.setdefault("best_project_id", None)
    report.setdefault("has_good_match", False)
    report.setdefault("missing_skills", [])
    report.setdefault("summary", "")
    return report


def rewrite_project_for_job(project: dict, analysis: dict, client: LLMClient) -> dict:
    """按岗位要求改写单个项目的简历描述，突出匹配点并量化。"""
    hl = project.get("highlights") or []
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "请针对目标岗位，把下面的项目经历改写成简历条目：表述口语自然、突出与岗位的匹配点、"
            "以动词开头、每条不超过40字、保留专业术语，不要编造不存在的数据。\n"
            "额外规则：能用数据证明的就用数据（量化成果/规模/指标/效率，只取原文出现的数字）；"
            "禁止写『获得XX认可/好评』等主观认可表述；摒弃学生思维，"
            "不用『学习能力强/快速上手/希望锻炼自己/熟练掌握（纯罗列）』等学生腔，"
            "用『负责/搭建/优化/提升/独立完成』等职业化动词，成果导向。\n"
            f"目标岗位：{analysis.get('position', '')}\n"
            f"核心技能：{'、'.join(s.get('skill', '') for s in analysis.get('key_skills', []))}\n"
            f"项目名：{project.get('name', '')}\n"
            f"我的角色：{project.get('role', '')}\n"
            f"技术栈：{'、'.join(project.get('tech_stack', []))}\n"
            f"项目描述：{project.get('description', '')}\n"
            f"已有亮点：{'；'.join(hl[:6])}\n"
            f"是否已部署：{'是' if project.get('deployed') else '否'}"
            f"{'，部署地址：' + project.get('deploy_url', '') if project.get('deployed') else ''}\n"
            "输出 JSON：\n"
            "{\n"
            '  "title": "项目条目标题（含我的角色，如 交通流量预测系统 · 核心开发）",\n'
            '  "bullets": ["3-5条要点，按岗位匹配度排序，首条写技术栈与职责，后续写量化成果"],\n'
            '  "deploy_line": "如已部署则写"已部署并可在线上访问：xxx"，未部署则为空字符串"\n'
            "}"
        )},
    ]
    return client.chat_json(messages, temperature=0.2, max_tokens=2000)


def analyze_experience(experience_text: str, analysis: dict, client: LLMClient) -> dict:
    """分析工作/实习经历与目标岗位的适配度，并改写为简历条目。

    核心规则：
    - 适配（能给简历加分）的经历 include=true 并改写；与岗位无关的 include=false 不写入简历
    - 能用数据证明的用数据（只取原文出现的数据，不编造），不写"获得XX认可/好评"类主观表述
    - 摒弃学生思维：不用"学习能力强/虚心请教/快速上手/希望锻炼自己"等学生腔，
      用"负责/搭建/优化/提升/独立完成"等职业化动词，成果导向
    """
    skills = "、".join(s.get("skill", "") for s in analysis.get("key_skills", []))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "下面是我的工作/实习经历。请逐条判断它与目标岗位的适配度并改写为简历条目。\n"
            f"目标岗位：{analysis.get('position', '')}\n"
            f"核心技能：{skills}\n"
            f"岗位职责：{'；'.join(analysis.get('responsibilities', []))}\n"
            "\n改写规则（必须严格遵守）：\n"
            "1. 与岗位无关、明显不适配、或没有可证明价值的经历 → include=false，不写入简历；\n"
            "2. 适配的经历 → include=true，并按岗位改写；\n"
            "3. 能用数据证明的就用数据：量化成果、规模、指标、时长、效率提升等，只使用原文出现的数据，不编造；\n"
            "4. 禁止写『获得XX认可/好评/表扬/肯定』这类主观认可表述；\n"
            "5. 摒弃学生思维：禁止『学习能力强』『虚心请教』『快速上手』『希望锻炼自己』『熟练掌握XX（纯罗列）』"
            "等学生腔表述，用『负责/搭建/优化/提升/独立完成/推动』等职业化动词，成果导向、专业简洁。\n"
            "\n工作/实习经历原文：\n" + experience_text +
            "\n输出 JSON：\n"
            "{\n"
            '  "items": [\n'
            "    {\n"
            '      "raw": "原文片段（用于展示对应关系）",\n'
            '      "include": true或false,\n'
            '      "reason": "判定理由，40字内，说明加分点或不写的原因",\n'
            '      "rewritten": "改写后的简历条目（1-3行，多行用\\n分隔；include=false时为空字符串）"\n'
            "    }\n"
            "  ]\n"
            "}"
        )},
    ]
    result = client.chat_json(messages, temperature=0.2, max_tokens=3000)
    result.setdefault("items", [])
    return result


def rank_oss_projects(candidates: list, analysis: dict, client: LLMClient) -> list:
    """从开源候选里挑出最适配的 3 个，并给出部署价值说明。"""
    if not candidates:
        return []
    brief = []
    for c in candidates:
        brief.append(
            f'- full_name="{c.get("full_name", "")}" stars={c.get("stars", 0)} '
            f'lang={c.get("language", "")} desc="{c.get("description", "")[:200]}" '
            f'url="{c.get("html_url", "")}"'
        )
    skills = "、".join(s.get("skill", "") for s in analysis.get("key_skills", []))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "下面是从 GitHub/Gitee 搜到的候选开源项目。请针对目标岗位挑出最适配的 3 个并排序，"
            "侧重：技术栈匹配、项目规模适中适合个人部署、能展示到简历上的价值。\n"
            f"目标岗位：{analysis.get('position', '')}\n"
            f"核心技能：{skills}\n"
            "候选：\n" + "\n".join(brief) +
            "\n输出 JSON：\n"
            "{\n"
            '  "picks": [\n'
            "    {\n"
            '      "full_name": "仓库全名，原样返回",\n'
            '      "reason": "为什么适配这个岗位（50字内）",\n'
            '      "deploy_notes": "部署注意点（如依赖、配置、环境要求），50字内"\n'
            "    }\n"
            "  ]\n"
            "}"
        )},
    ]
    try:
        result = client.chat_json(messages, temperature=0.1, max_tokens=2000)
        picks = result.get("picks", [])
    except LLMError:
        # 模型排序失败时按 star 数兜底
        picks = [
            {"full_name": c["full_name"], "reason": "按仓库热度排序的候选项目",
             "deploy_notes": ""}
            for c in sorted(candidates, key=lambda x: x.get("stars", 0), reverse=True)[:3]
        ]

    merged = []
    for pick in picks:
        c = next((x for x in candidates if x.get("full_name") == pick.get("full_name")), None)
        if c is None:
            continue
        item = dict(c)
        item["pick_reason"] = pick.get("reason", "")
        item["deploy_notes"] = pick.get("deploy_notes", "")
        merged.append(item)
    return merged


def analyze_project_text(text: str, client: LLMClient) -> Optional[dict]:
    """把用户自由粘贴的项目描述文本结构化（供前端回填表单，不直接入库）。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": (
            "把下面的项目描述文本结构化，输出 JSON：\n"
            "{\n"
            '  "name": "项目名",\n'
            '  "role": "我的角色",\n'
            '  "tech_stack": ["技术栈"],\n'
            '  "description": "项目简介（120字内）",\n'
            '  "highlights": ["亮点/量化成果，逐条"],\n'
            '  "source_url": "项目链接，文本中出现URL则原样提取，没有则为空字符串"\n'
            "}\n"
            "注意：不要编造原文没有的信息，量化数字只取原文出现的。\n" + text
        )},
    ]
    result = client.chat_json(messages, temperature=0.1, max_tokens=2000)
    result.setdefault("name", "")
    result.setdefault("role", "")
    result.setdefault("tech_stack", [])
    result.setdefault("description", "")
    result.setdefault("highlights", [])
    result.setdefault("source_url", "")
    if isinstance(result.get("highlights"), str):
        result["highlights"] = [h.strip() for h in result["highlights"].split("\n") if h.strip()]
    if isinstance(result.get("tech_stack"), str):
        result["tech_stack"] = [t.strip() for t in result["tech_stack"].replace("，", ",").split(",") if t.strip()]
    return result
