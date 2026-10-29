"""resume-agent 求职简历助手 —— Flask 主应用。

工作流：
  设置(豆包Key/GitHub/Gitee) -> 个人资料 -> 项目库 -> 岗位分析匹配
  -> 有匹配：生成简历 | 无匹配：开源搜索 -> 推荐项目 -> 部署确认 -> 写进简历
"""
from __future__ import annotations

import os
from datetime import datetime

from flask import Flask, flash, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from resume_agent import job_analyzer, oss_client, resume_builder, store
from resume_agent.llm_client import LLMClient, LLMError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = "resume-agent-local-only"
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 上传上限 10MB

ALLOWED_TEMPLATE_EXTS = {".docx"}


def get_client() -> LLMClient:
    cfg = store.get_llm_config()
    return LLMClient(cfg["api_key"], cfg["base_url"], cfg["model"])


def project_card(p: dict, score: int | None = None, extra: dict | None = None) -> dict:
    """前端展示用的项目卡片。"""
    return {
        "id": p.get("id"),
        "name": p.get("name", ""),
        "role": p.get("role", ""),
        "tech_stack": p.get("tech_stack", []),
        "description": p.get("description", ""),
        "highlights": p.get("highlights", []),
        "source": p.get("source", "user"),
        "source_url": p.get("source_url", ""),
        "deployed": bool(p.get("deployed")),
        "deploy_url": p.get("deploy_url", ""),
        "score": score,
        "extra": extra or {},
    }


# ---------------------------------------------------------------- 首页

@app.route("/")
def index():
    projects = store.list_projects()
    analysis = store.load_analysis()
    report = store.load_report()
    cfg = store.get_llm_config()
    provider_label = store.PROVIDER_PRESETS.get(cfg["provider"], {}).get("label", cfg["provider"])
    return render_template("index.html",
                           llm_cfg={"provider": cfg["provider"], "label": provider_label,
                                    "model": cfg["model"], "key_ok": bool(cfg["api_key"])},
                           settings_ok=bool(cfg["api_key"]),
                           profile_ok=bool(store.load_profile().get("name")),
                           project_count=len(projects),
                           template_count=len(store.list_uploaded_templates()),
                           resume_count=len(store.list_generated_resumes()),
                           has_analysis=analysis is not None,
                           has_report=report is not None,
                           last_position=(analysis or {}).get("position", ""),
                           has_good_match=bool(report and report.get("has_good_match")))


# ---------------------------------------------------------------- 连接设置

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    if request.method == "POST":
        s = store.load_settings()
        provider = request.form.get("llm_provider", "doubao")
        if provider not in store.PROVIDER_PRESETS:
            provider = "doubao"
        s["llm_provider"] = provider
        for p in store.PROVIDER_PRESETS:
            s[f"{p}_api_key"] = request.form.get(f"{p}_api_key", "").strip()
            s[f"{p}_base_url"] = request.form.get(f"{p}_base_url", "").strip() or store.PROVIDER_PRESETS[p]["base_url"]
            s[f"{p}_model"] = request.form.get(f"{p}_model", "").strip() or store.PROVIDER_PRESETS[p]["model"]
        s["github_token"] = request.form.get("github_token", "").strip()
        s["gitee_token"] = request.form.get("gitee_token", "").strip()
        store.save_settings(s)
        cfg = store.get_llm_config(s)
        flash(f"连接设置已保存（当前使用：{store.PROVIDER_PRESETS[cfg['provider']]['label']} · {cfg['model'] or '未填模型' }）", "ok")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", settings=store.load_settings(),
                           providers=store.PROVIDER_PRESETS)


# ---------------------------------------------------------------- 简历模板（专属页）

@app.route("/templates", methods=["GET"])
def templates_page():
    return render_template("templates.html",
                           templates=store.list_uploaded_templates())


@app.route("/template/upload", methods=["POST"])
def template_upload():
    f = request.files.get("template")
    if not f or not f.filename:
        flash("请选择要上传的 .docx 模板文件", "err")
        return redirect(url_for("templates_page"))
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_TEMPLATE_EXTS:
        flash("只支持 .docx 格式的模板", "err")
        return redirect(url_for("templates_page"))
    base = secure_filename(os.path.splitext(f.filename)[0]) or f"template_{int(__import__('time').time())}"
    safe = base + ext
    os.makedirs(store.TEMPLATE_DIR, exist_ok=True)
    f.save(os.path.join(store.TEMPLATE_DIR, safe))
    flash(f"模板《{safe}》上传成功。可在模板中放 {{{{NAME}}}} {{{{PROJECTS}}}} 等占位符；没有占位符时会自动追加项目经历", "ok")
    return redirect(url_for("templates_page"))


@app.route("/template/delete/<path:filename>", methods=["POST"])
def template_delete(filename):
    if store.delete_template(filename):
        flash("模板已删除", "ok")
    else:
        flash("模板不存在", "err")
    return redirect(url_for("templates_page"))


# ---------------------------------------------------------------- 个人资料

@app.route("/profile", methods=["GET", "POST"])
def profile_page():
    if request.method == "POST":
        data = {k: request.form.get(k, "") for k in store.EMPTY_PROFILE}
        store.save_profile(data)
        flash("个人资料已保存", "ok")
        return redirect(url_for("profile_page"))
    return render_template("profile.html", profile=store.load_profile())


# ---------------------------------------------------------------- 项目库

@app.route("/projects", methods=["GET", "POST"])
def projects_page():
    if request.method == "POST":
        p = {
            "name": request.form.get("name", "").strip(),
            "role": request.form.get("role", "").strip(),
            "tech_stack": [t.strip() for t in request.form.get("tech_stack", "").replace("，", ",").split(",") if t.strip()],
            "description": request.form.get("description", "").strip(),
            "highlights": request.form.get("highlights", "").strip(),
            "source_url": request.form.get("source_url", "").strip(),
        }
        if not p["name"]:
            flash("项目名称不能为空", "err")
            return redirect(url_for("projects_page"))
        store.add_project(p)
        flash(f"项目《{p['name']}》已加入项目库", "ok")
        return redirect(url_for("projects_page"))
    edit_id = request.args.get("edit", "")
    edit_project = store.get_project(edit_id) if edit_id else None
    if edit_project:
        edit_project["highlights_text"] = "\n".join(edit_project.get("highlights") or [])
        edit_project["tech_stack_text"] = ", ".join(edit_project.get("tech_stack") or [])
    projects = [project_card(p) for p in store.list_projects()]
    return render_template("projects.html", projects=projects, edit_project=edit_project)


@app.route("/projects/edit/<project_id>", methods=["POST"])
def projects_edit(project_id):
    highlights = [h.strip() for h in request.form.get("highlights", "").split("\n") if h.strip()]
    p = {
        "name": request.form.get("name", "").strip(),
        "role": request.form.get("role", "").strip(),
        "tech_stack": [t.strip() for t in request.form.get("tech_stack", "").replace("，", ",").split(",") if t.strip()],
        "description": request.form.get("description", "").strip(),
        "highlights": highlights,
        "source_url": request.form.get("source_url", "").strip(),
    }
    if not p["name"]:
        flash("项目名称不能为空", "err")
        return redirect(url_for("projects_page", edit=project_id))
    if not store.update_project(project_id, p):
        flash("项目不存在", "err")
        return redirect(url_for("projects_page"))
    flash("项目已更新", "ok")
    return redirect(url_for("projects_page"))


@app.route("/projects/parse", methods=["POST"])
def projects_parse():
    """AI 识别：粘贴项目描述，返回结构化 JSON 供前端回填表单（不直接入库）。"""
    text = request.form.get("text", "").strip()
    if not text:
        return {"ok": False, "error": "请先粘贴项目描述文本"}, 400
    try:
        client = get_client()
        parsed = job_analyzer.analyze_project_text(text, client)
    except LLMError as e:
        return {"ok": False, "error": str(e)}, 400
    if not parsed or not parsed.get("name"):
        return {"ok": False, "error": "AI 未能识别出项目名称，请补充描述或重试"}, 400
    return {"ok": True, "project": parsed}


@app.route("/projects/delete/<project_id>", methods=["POST"])
def projects_delete(project_id):
    if store.delete_project(project_id):
        flash("项目已删除", "ok")
    else:
        flash("项目不存在", "err")
    return redirect(url_for("projects_page"))


@app.route("/projects/<project_id>/deployed", methods=["POST"])
def projects_deployed(project_id):
    url = request.form.get("deploy_url", "").strip()
    if not url:
        flash("请填写部署后的访问地址（URL）", "err")
        return redirect(url_for("recommend_page"))
    p = store.mark_deployed(project_id, url)
    if not p:
        flash("项目不存在", "err")
        return redirect(url_for("projects_page"))
    flash(f"《{p.get('name')}》已标记为部署完成，可在「生成简历」页勾选写入", "ok")
    return redirect(url_for("resume_page"))


# ---------------------------------------------------------------- 岗位分析

@app.route("/analyze", methods=["GET", "POST"])
def analyze_page():
    if request.method == "POST":
        job_text = request.form.get("job_text", "").strip()
        if len(job_text) < 20:
            flash("岗位信息太短，请粘贴完整的岗位描述（至少 20 字）", "err")
            return redirect(url_for("analyze_page"))
        try:
            client = get_client()
            analysis = job_analyzer.analyze_job(job_text, client)
            projects = store.list_projects()
            report = job_analyzer.match_projects(analysis, projects, client)
            store.save_analysis(analysis)
            store.save_report(report)
            store.add_history({
                "job_text": job_text[:2000],
                "analysis": analysis,
                "report": report,
            })
            flash("岗位分析完成，已存入历史记录", "ok")
        except LLMError as e:
            flash(str(e), "err")
        return redirect(url_for("analyze_page"))

    # GET：优先展示指定历史记录，否则展示最近一次
    history_id = request.args.get("history", "")
    if history_id:
        item = store.get_history(history_id)
        if item:
            analysis = item.get("analysis") or {}
            report = item.get("report") or {}
            # 同步为当前缓存，便于「生成简历」直接使用该岗位
            store.save_analysis(analysis)
            store.save_report(report)
            flash(f"已载入历史记录：{item.get('time')}", "ok")
    else:
        analysis = store.load_analysis()
        report = store.load_report()
    history = store.list_history()

    cards = []
    if report and report.get("results"):
        projects = {p["id"]: p for p in store.list_projects()}
        for r in report["results"]:
            p = projects.get(r.get("id"))
            if not p:
                continue
            cards.append(project_card(p, score=r.get("score"),
                                      extra={"verdict": r.get("verdict"), "reason": r.get("reason"),
                                             "highlight_points": r.get("highlight_points", []),
                                             "gap": r.get("gap", "")}))
    return render_template("analyze.html",
                           analysis=analysis, report=report, cards=cards, history=history)


@app.route("/analyze/delete/<history_id>", methods=["POST"])
def analyze_delete(history_id):
    if store.delete_history(history_id):
        flash("历史记录已删除", "ok")
    else:
        flash("记录不存在", "err")
    return redirect(url_for("analyze_page"))


# ---------------------------------------------------------------- 开源推荐

@app.route("/recommend", methods=["GET"])
def recommend_page():
    data = store.load_oss_candidates()
    if isinstance(data, dict):
        candidates = data.get("candidates", [])
        query = data.get("query", "")
    else:
        candidates = data or []
        query = ""
    analysis = store.load_analysis()
    report = store.load_report()
    if not query and analysis:
        query = oss_client.build_query(analysis)
    return render_template("recommend.html",
                           analysis=analysis, report=report,
                           candidates=candidates,
                           query=query or "")


@app.route("/recommend/search", methods=["POST"])
def recommend_search():
    analysis = store.load_analysis()
    if not analysis:
        flash("请先在「岗位分析」页完成岗位解析", "err")
        return redirect(url_for("recommend_page"))
    settings = store.load_settings()
    manual = request.form.get("keywords", "").strip()
    try:
        client = get_client()
        result = oss_client.search_any(analysis, settings, manual=manual)
        if not result["candidates"]:
            err_text = "；".join(result["errors"]) or "两个平台都没有搜到结果"
            flash(f"未找到候选项目：{err_text}", "err")
            return redirect(url_for("recommend_page"))
        # LLM 精排：挑最适配的 3 个
        picks = job_analyzer.rank_oss_projects(result["candidates"], analysis, client)
        result["candidates"] = picks or result["candidates"][:3]
        result["query"] = result.get("query", "")
        store.save_oss_candidates(result)
        flash(f"已从 {result['platform']} 搜索并挑选出 {len(result['candidates'])} 个适配项目", "ok")
    except LLMError as e:
        flash(str(e), "err")
    return redirect(url_for("recommend_page"))


@app.route("/recommend/select/<int:idx>", methods=["POST"])
def recommend_select(idx):
    data = store.load_oss_candidates()
    candidates = data.get("candidates", []) if isinstance(data, dict) else data
    if idx < 0 or idx >= len(candidates):
        flash("候选索引无效", "err")
        return redirect(url_for("recommend_page"))
    cand = candidates[idx]
    # 已存在则复用
    existing = next((p for p in store.list_projects() if p.get("source_url") == cand.get("html_url")), None)
    if existing:
        flash("该项目已在项目库中，可直接部署或生成简历", "ok")
        return redirect(url_for("deploy_page", project_id=existing["id"]))
    project = oss_client.to_project(cand)
    # 补充技术栈与部署说明
    settings = store.load_settings()
    readme = oss_client.fetch_readme(cand.get("full_name", ""), cand.get("platform", "github"),
                                     settings.get("github_token", "") if cand.get("platform") == "github" else "")
    project["readme_preview"] = readme
    project["pick_reason"] = cand.get("pick_reason", "")
    project["deploy_notes"] = cand.get("deploy_notes", "")
    project["stars"] = cand.get("stars", 0)
    created = store.add_project(project)
    flash(f"项目《{created['name']}》已加入项目库，请参考部署指引完成部署", "ok")
    return redirect(url_for("deploy_page", project_id=created["id"]))


@app.route("/deploy/<project_id>", methods=["GET"])
def deploy_page(project_id):
    p = store.get_project(project_id)
    if not p:
        flash("项目不存在", "err")
        return redirect(url_for("recommend_page"))
    # 未缓存 README 时尝试抓取
    if not p.get("readme_preview"):
        settings = store.load_settings()
        token = settings.get("github_token", "") if p.get("source") == "github" else ""
        p["readme_preview"] = oss_client.fetch_readme(p.get("name", ""), p.get("source", "github"), token)
    extra = {"pick_reason": p.get("pick_reason", ""), "deploy_notes": p.get("deploy_notes", "")}
    return render_template("deploy.html", project=project_card(p, extra=extra), readme=p.get("readme_preview", ""))


# ---------------------------------------------------------------- 简历生成

@app.route("/resume", methods=["GET"])
def resume_page():
    templates = store.list_uploaded_templates()
    resumes = store.list_generated_resumes()
    analysis = store.load_analysis()
    projects = [project_card(p) for p in store.list_projects()]
    profile = store.load_profile()
    return render_template("resume.html",
                           templates=templates, resumes=resumes,
                           position=(analysis or {}).get("position", ""),
                           projects=projects,
                           experience_text=profile.get("experience", ""),
                           exp_result=store.load_experience_analysis())


@app.route("/resume/generate", methods=["POST"])
def resume_generate():
    template_name = request.form.get("template", "").strip()
    if not template_name:
        flash("请先选择简历模板", "err")
        return redirect(url_for("resume_page"))
    selected_ids = request.form.getlist("project_ids")
    if not selected_ids:
        flash("请至少勾选一个要写入简历的项目", "err")
        return redirect(url_for("resume_page"))

    template_path = os.path.join(store.TEMPLATE_DIR, template_name)
    profile = store.load_profile()
    analysis = store.load_analysis() or {}
    try:
        client = get_client()
    except LLMError as e:
        flash(str(e), "err")
        return redirect(url_for("resume_page"))

    entries = []
    for pid in selected_ids:
        p = store.get_project(pid)
        if not p:
            continue
        try:
            rewrite = job_analyzer.rewrite_project_for_job(p, analysis, client)
            bullets = rewrite.get("bullets", [])
            deploy_line = rewrite.get("deploy_line", "")
            if not deploy_line and p.get("deployed") and p.get("deploy_url"):
                deploy_line = f"已部署并可在线上访问：{p['deploy_url']}"
            entries.append({
                "title": rewrite.get("title") or p.get("name", ""),
                "bullets": bullets,
                "deploy_line": deploy_line,
            })
        except LLMError as e:
            # 单个项目改写失败不阻断整体，降级为原文
            hl = p.get("highlights") or []
            entries.append({
                "title": f"{p.get('name', '')} · {p.get('role', '')}" if p.get("role") else p.get("name", ""),
                "bullets": ([p.get("description", "")] + [f"• {h}" for h in hl])[:5],
                "deploy_line": (f"已部署并可在线上访问：{p['deploy_url']}"
                                if p.get("deployed") and p.get("deploy_url") else ""),
            })
            flash(f"《{p.get('name')}》改写失败已降级为原文：{e}", "warn")

    if not entries:
        flash("没有可写入的项目，请先在项目库添加项目", "err")
        return redirect(url_for("resume_page"))

    # ---- 工作经历：按岗位适配度过滤 + 改写 ----
    filter_exp = request.form.get("filter_experience") == "on"
    experience_text = (profile.get("experience") or "").strip()
    exp_lines = None
    exp_summary = {"included": 0, "filtered": 0}
    if experience_text:
        if filter_exp and analysis:
            try:
                exp_result = job_analyzer.analyze_experience(experience_text, analysis, client)
                store.save_experience_analysis({
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "position": analysis.get("position", ""),
                    "items": exp_result.get("items", []),
                })
                exp_lines = []
                for it in exp_result.get("items", []):
                    if it.get("include") and str(it.get("rewritten") or "").strip():
                        exp_lines.extend(l for l in str(it["rewritten"]).split("\n") if l.strip())
                        exp_summary["included"] += 1
                    else:
                        exp_summary["filtered"] += 1
                if not exp_lines:
                    exp_lines = None
            except LLMError as e:
                flash(f"工作经历适配分析失败，已按原文写入：{e}", "warn")
        # 未开启过滤、无岗位分析或分析失败时走原文
        if exp_lines is None:
            exp_lines = [l for l in experience_text.split("\n") if l.strip()]

    try:
        out_path = resume_builder.build_resume(
            profile, entries, template_path,
            position=analysis.get("position", ""),
            out_dir=store.RESUME_DIR,
            experience_lines=exp_lines,
        )
        fname = os.path.basename(out_path)
        msg = f"简历已生成：{fname}，可在下方列表下载"
        if exp_summary["included"] or exp_summary["filtered"]:
            msg += f"；工作经历已按岗位筛选：写入 {exp_summary['included']} 条，过滤 {exp_summary['filtered']} 条"
        flash(msg, "ok")
    except resume_builder.ResumeBuildError as e:
        flash(str(e), "err")
    except Exception as e:  # python-docx 各种模板异常
        flash(f"简历生成失败：{e}。请确认模板未损坏", "err")
    return redirect(url_for("resume_page"))


@app.route("/resume/download/<path:filename>")
def resume_download(filename):
    # 只用 basename 防止路径穿越；保留中文文件名原样
    name = os.path.basename(filename)
    path = os.path.join(store.RESUME_DIR, name)
    if not os.path.exists(path):
        flash("文件不存在", "err")
        return redirect(url_for("resume_page"))
    return send_file(path, as_attachment=True, download_name=name)


@app.route("/resume/delete/<path:filename>", methods=["POST"])
def resume_delete(filename):
    if store.delete_resume(filename):
        flash("简历已删除", "ok")
    else:
        flash("文件不存在", "err")
    return redirect(url_for("resume_page"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print("=" * 60)
    print("resume-agent 求职简历助手已启动")
    print(f"请用浏览器打开： http://127.0.0.1:{port}")
    print("按 Ctrl+C 停止服务")
    print("=" * 60)
    app.run(host="127.0.0.1", port=port, debug=False)
