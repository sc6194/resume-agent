# resume-agent 求职简历助手

针对岗位自动匹配你做过的最适配项目并生成 Word 简历的本地 Agent 工具。
**岗位没有适配项目时，自动去 GitHub / Gitee 搜索适配的开源项目，推荐给你部署，部署成功后再写进简历。**

## 功能一览

| 功能 | 说明 |
| --- | --- |
| 个人资料管理 | 姓名、教育背景、技能、实习经历、证书等，写入简历模板占位符 |
| 项目库管理 | 手动录入 / 粘贴文本 AI 结构化导入，记录技术栈、亮点、部署状态 |
| 岗位分析 | 大模型（豆包 / OpenAI / DeepSeek 三选一）解析岗位职责、技能权重、任职要求 |
| 项目匹配 | 把项目库与岗位逐项评分（0-100），给出匹配理由、建议突出的点、缺失技能 |
| 开源推荐 | 无匹配时按岗位技能在 GitHub / Gitee 搜索，LLM 精排 Top3，自动抓取 README 给部署指引 |
| 部署确认 | 填部署地址即标记「已部署」，随后可写入简历 |
| 简历生成 | 套用你上传的 .docx 模板（占位符替换 / 无占位符自动追加），AI 按岗位改写项目描述并量化 |
| AI 识别填写 | 项目库页粘贴项目描述，自动识别并填好表单，确认后再入库 |

## 目录结构

```
resume-agent/
├── app.py                  # Flask 主应用（所有路由与流程编排）
├── requirements.txt        # 依赖清单
├── .env.example            # API 配置参考样例（实际请在网页「设置」页填写）
├── resume_agent/
│   ├── store.py            # JSON 数据层（设置/资料/项目库/报告，含多服务商配置）
│   ├── llm_client.py       # 大模型客户端（豆包/OpenAI/DeepSeek 等 OpenAI 兼容接口）
│   ├── job_analyzer.py     # 岗位解析、项目匹配评分、描述改写、候选排序
│   ├── oss_client.py       # GitHub / Gitee 搜索、README 抓取
│   └── resume_builder.py   # Word 模板填充（保留模板格式）
├── templates/              # 页面模板
├── static/                 # 样式
└── data/                   # 运行数据（自动生成：设置、项目库、简历、模板）
```

## 环境要求

- Windows / macOS / Linux 均可
- Python 3.9+（开发调试建议用 PyCharm，本说明以 PyCharm 为例）

## 安装步骤（PyCharm 为例）

1. **下载/复制本项目**到你的工作目录，例如 `D:\projects\resume-agent`。
2. 用 PyCharm 打开该目录（File → Open，选择 `resume-agent` 文件夹）。
3. 创建虚拟环境：PyCharm 右下角提示“Python Interpreter”时点 **Add Interpreter → Add Local Interpreter → Virtualenv Environment → New**，选择 Python 3.9+ 版本后确认。
4. 安装依赖：打开 PyCharm 底部 **Terminal**，执行：
   ```
   pip install -r requirements.txt
   ```
5. 配置大模型 API Key（在网页「连接设置」页完成，**豆包 / OpenAI / DeepSeek / 自定义 四选一**）：
   - **豆包**：登录 [火山方舟控制台](https://console.volcengine.com/ark)（手机号注册，新用户有免费额度）→「API Key 管理」→ 创建 API Key；在「开通管理」开通模型并记住**模型 ID**（如 `doubao-seed-1.6-flash`，或你的接入点 ID）
   - **OpenAI**：在 [platform.openai.com](https://platform.openai.com) 创建 API Key，模型如 `gpt-4o-mini`
   - **DeepSeek**：在 [platform.deepseek.com](https://platform.deepseek.com) 创建 API Key，模型如 `deepseek-chat`
   - **自定义**：任意 OpenAI 兼容接口（第三方中转站、本地 Ollama 等），接口地址、Key、模型名都自行填写
   - 四家都支持「接口地址 + 模型 ID」自定义，前三家默认值已预填
6. （可选）GitHub Token：
   - [GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)](https://github.com/settings/tokens)
   - Generate new token，只勾选 `public_repo` 权限，复制保存
7. （可选）Gitee Token：[Gitee 个人设置 → 私人令牌](https://gitee.com/profile/personal_access_tokens)，只勾选 `projects` 权限

## 启动运行

在 PyCharm Terminal（或任意终端）执行：

```
python app.py
```

看到 `resume-agent 求职简历助手已启动` 后，用浏览器打开：

```
http://127.0.0.1:5000
```

> 端口冲突时可指定：`PORT=5001 python app.py`（Windows PowerShell 用 `$env:PORT="5001"; python app.py`）。

## 使用流程（按工作台步骤）

1. **连接设置**：选择大模型服务商（豆包 / OpenAI / DeepSeek / 自定义接口）并填对应 API Key（必填）→ 保存；填 GitHub/Gitee Token（可选）。首页会显示当前使用的模型。
2. **简历模板**：上传你的 `.docx` 简历模板（专属页面，可删除）。
3. **个人资料**：填姓名、学校、技能等；在「实习/工作经历」粘贴你的经历（每行或每段一条）。生成简历时会自动判断每条经历与岗位的适配度，**能给简历加分才写入**，与岗位无关的不写。
4. **项目库**：手动添加项目，或在上方粘贴项目描述点「AI 识别并自动填写」核对后入库；支持编辑已有项目。
5. **岗位分析**：把招聘页面的职位描述整段粘贴 → 点「开始分析并匹配」。每次分析都会存入历史记录，可回看、可对任意一条直接生成简历。
   - 有适配项目（匹配度 ≥ 70）：直接去「生成简历」。
   - 无适配项目：点「去开源平台找项目」→ 在「开源推荐」页确认/修改搜索关键词（默认自动精简为 1-2 个核心词）→ 搜索 → 选一个候选 → 按部署指引克隆、安装依赖、本地跑起来 → 填访问地址「确认部署完成」→ 自动进入「生成简历」页。
6. **生成简历**：选模板 → 勾选项目（AI 按岗位改写描述并量化）→ 工作经历按岗位自动筛选（可在「生成简历」页查看最近一次分析：哪些写入、哪些过滤及原因）→ 生成 → 下载 `.docx`。

> 简历改写统一遵循：能用数据证明的就用数据（量化成果/规模/指标，只取原文出现的数据，不编造）；不写"获得XX认可/好评"这类主观认可表述；摒弃学生思维（不写"学习能力强/虚心请教/熟练掌握（纯罗列）"），用"负责/搭建/优化/提升/独立完成"等职业化动词、成果导向。

## 简历模板写法

推荐在模板里放占位符（大小写不敏感），程序原位替换并保留你的版式：

```
{{NAME}}  {{PHONE}}  {{EMAIL}}  {{CITY}}
{{SCHOOL}}  {{MAJOR}}  {{DEGREE}}  毕业时间：{{GRADUATION}}
求职意向：{{TARGET_POSITION}}
个人简介：{{SUMMARY}}
技能：{{SKILLS}}
项目经历：
{{PROJECTS}}        ← 项目条目会整段插入到这里
实习经历：
{{EXPERIENCE}}
证书：{{CERTIFICATES}}    语言：{{LANGUAGES}}
```

模板里**没有**占位符也没关系：程序会找「项目经历/项目经验」标题，在其后插入项目条目；找不到该标题就追加到文末。

## 数据与隐私

- 所有数据只存在本项目 `data/` 目录的 JSON 和 docx 文件中，不联网上传。
- 仅岗位分析、匹配、简历改写会调用所选大模型 API（按量计费，新用户一般有免费额度）；开源搜索直接调用 GitHub/Gitee 公开 API。
- 本工具**只监听 127.0.0.1**，请勿修改 host 暴露到公网。

## 常见问题

| 问题 | 处理 |
| --- | --- |
| 提示“API Key 无效” | 到所用服务商的控制台核对 Key 是否复制完整、是否已创建；确认「设置」页选中的服务商和 Key 一致 |
| 提示“模型 ID 不存在或未开通” | 到服务商控制台确认模型 ID 是否开通，并在设置页更新 |
| 切换服务商后仍报错 | 确认「设置」页保存时选中的服务商正确；不同服务商的 Key 不通用 |
| GitHub 搜索限流（403） | 匿名 60 次/小时。到设置页填 GitHub Token 后重试 |
| GitHub 连接失败/超时 | 网络直连 GitHub 不稳定时可改用 Gitee（两个平台都支持）；有代理时先开代理再搜索 |
| 生成的简历没有项目内容 | 模板用了占位符但名字写错（如 `{{PROJECT}}` 少个 S），对照上表检查；或改用无占位符模板 |
| 生成的简历版式错乱 | 模板可能结构特殊，建议在模板中改用占位符模式，程序会保留模板段落格式 |

## 开发调试

- 单元自检：`python -m compileall resume_agent app.py` 检查语法。
- 想本地起服务看日志：改 `app.py` 末尾 `app.run(debug=True)` 即可（仅调试用）。
