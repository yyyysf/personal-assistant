# 项目总览：My Private Assistant（私人网页助手）
一句话定位：面向我个人使用、网页前端交互的私人智能助手；第一阶段仅本地开发调试，待原型全部稳定可用之后，再选择部署到香港轻量云或者NAS Docker。
- 主力LLM：DeepSeek V4-Flash（OpenAI兼容接口），用于摘要、总结、学习路线动态生成、自然语言规划、每周AI复盘
- 开发工具：Claude Code CLI + VSCode
- 仓库：GitHub Private私有仓库，源码支持本地脚本自动commit&push备份
- 数据库：SQLite；后续地理旅游模块升级为 Postgres + PostGIS
- MCP 运行模式约定：本地调试使用 stdio；如果后续上生产部署，线上环境切换为 SSE/Streamable HTTP 远程模式
- 核心原则：**模块化、可扩展、增量迭代**，优先稳定可用，先落地首页仪表盘，再逐个打通业务板块；优先实现半自动稳妥方案，高风险爬虫后置作为可选扩展。
- ui设计风格: 苹果风格，要求有响应式配置

# 分支 & 上线流程规范
分支划分：
- main：生产线上分支，开启分支保护，禁止直接push，仅通过PR合并更新；合并main自动触发GitHub Actions流水线，部署到腾讯轻量服务器
- dev：开发分支，所有功能迭代、UI修改、接口变更全部在dev分支开发

强制流程：
1. 所有开发、代码改动在 dev 分支进行；
2. 改动完成后，本地启动完整服务，由我人工测试全部相关功能，确认无BUG、交互符合预期；
3. 测试通过，提交推送dev，发起 dev → main 的 Pull Request；
4. PR必须由我手动审阅、手动点击合并，禁止任何自动合并main；
5. 合并成功触发 GitHub Actions：SSH连上腾讯轻量服务器，执行 git pull origin main → systemctl重启assistant.service → 服务存活自检；
6. Actions部署任务失败时，保留线上原有版本，不会覆盖坏版本；
7. 服务器Deploy Key仅用于服务器免密拉取代码；GitHub Actions使用独立SSH私钥用于流水线远程ssh部署。

## 核心页面：首页总仪表盘（对标参考的Obsidian工位看板）
首页为默认入口，实现全局汇总视图：
- 全局统计卡片：本周任务执行率、已完成数量、今日完成数量、连续记录天数
- Tab分区切换：总览｜科研｜AI视频学习｜AI音乐学习｜书单阅读｜旅游规划｜Todo目标管理
- 可视化：月度热力日历、各板块进度环形图、当前学习/阅读进度条
- AI复盘卡片：读取本周全部记录，调用LLM生成本周复盘总结 + 下周行动建议
- 今日焦点区域：展示今日待办、今日新论文、今日学习任务

## 六大业务板块需求
### 1. 日常任务 Todo & 目标管理板块
- 功能：任务清单、待办、优先级、标签、截止时间、完成记录、历史归档、目标拆解
- 页面：看板视图、今日待办、历史归档，数据汇总同步到首页仪表盘

### 2. 科研板块（Zotero 强联动）
- 自动每日抓取 arXiv cs.AI（大模型方向）新论文，LLM生成摘要，支持一键导入Zotero文库，自动打标签
- 读取Zotero笔记、注释，定时生成阶段性文献复盘
- 网页面板：今日论文推荐列表、已入库记录、阅读汇总报告，每条附带跳转原论文链接
- 使用MCP：zotero-mcp-server、Academia MCP、Semantic Scholar MCP、Scholar Feed MCP

### 3. 小红书收藏 & 书单电子书板块（第一版半自动方案）
- 第一阶段方案：使用油猴脚本导出小红书收藏JSON文件，网页提供上传入口，后端解析笔记、提取博主推荐书单；**暂不实现自动Cookie爬虫**
- 自动Cookie爬虫MCP标记为【后期可选扩展】，严格约束：仅自用、每日最多一次增量同步、限流防风控
- 配套MCP：libgen-mcp、Gutenberg MCP（公版电子书检索）
- 输出：书单清单、书籍资源链接，支持导出TXT；网页展示笔记摘要、封面、原文跳转链接

### 4. AI & 计算机前沿资讯日报
- 订阅RSS源：arXiv cs.AI、HuggingFace Blog、Hacker News、AI实验室博客
- 定时聚合、LLM精简总结，生成带原链接的清单，支持按日/按月归档查看
- 使用MCP：feed-mcp（RSS MCP）
- 页面：简报列表、时间线、搜索历史简报；简报汇总统计同步至首页仪表盘

### 5. 动态学习路线板块（先实现AI视频、AI音乐两个子模块，可切换）
- 依靠 memory-mcp 持久化存储学习进度、已学知识点、掌握程度、待学任务
- 每次访问读取记忆交给LLM，动态调整学习路径，拆分每日微小学习任务
- 配套：B站/Youtube搜索MCP检索教程链接，加入学习清单
- 页面：学习仪表盘、今日学习任务、进度记录、历史笔记；进度数据汇总到首页总看板

### 6. 旅游规划 & 地图标记板块
- 前端地图组件：Leaflet（开源免费，网页渲染世界地图，支持缩放、打点、标记）
- MCP：OSM MCP优先，地名转坐标、景点检索、路线规划
- 输入来源：手动录入游记、后续可导入小红书游记文本
- 数据存储：去过地点、游记、照片备注、规划草稿全部存入数据库
- 页面：交互式地图、行程方案编辑器、历史旅行档案

## 技术栈约定（严格遵守）
- 后端：FastAPI + Pydantic + SQLAlchemy
- 调度：APScheduler（服务内定时任务）
- 前端：Jinja2模板 + HTMX（主交互） + Alpine.js（局部轻量状态、tab切换、进度组件），优先轻量，不做完整React SPA
- MCP Host：支持同时管理多个SSE/stdio MCP服务
- 部署：本地优先开发验证；后续可选择Docker打包，使用systemd托管服务
- 备份规则：
  1. 源码：本地脚本自动提交推送至GitHub私有仓库
  2. SQLite业务数据库：不和代码混存；可选单独加密压缩后推送到独立的私有备份仓库，不混入源码仓库
  3. 禁止明文数据库提交到源码仓库

## 目录结构规范（新建文件遵循）
src/
├── api/            # FastAPI 路由，统一前缀 /api/v1
├── mcp_host/       # MCP Host 调度代码、MCP 服务配置
├── mcp_servers/    # 自建私有 MCP（小红书爬虫 MCP 放这里，标记可选）
├── core/           # 配置、env 加载、日志、安全工具
├── models/         # SQLAlchemy ORM 模型
├── scheduler/      # 定时任务定义（论文抓取、rss 同步）
├── llm/            # DeepSeek V4-Flash 调用封装、摘要 / 复盘 prompt 模板
templates/          # Jinja 页面模板，首页仪表盘放在 templates/dashboard.html
static/             # css、js、地图静态资源、alpine/htmx 脚本
tests/              # 单元测试
.env.example        # 样例环境变量，真实 .env 不提交 git
CLAUDE.md
.gitignore
auto_backup.sh/auto_backup.bat  # 本地自动 git 备份脚本

## 编码规范 & 硬性约束（红线，不可违反）
1. Python 遵循 PEP8，函数必须加类型注解；单行最长100字符
2. **所有密钥、Token、Cookie、Zotero Key、DeepSeek Key 只放在 .env**，绝对禁止硬编码进代码、禁止提交进Git；.env、*.db、cookie缓存文件加入 .gitignore
3. 区分本地调试与线上：新增MCP默认先写stdio版本本地验证；上线必须改成SSE
4. 爬虫类任务（小红书）如果后续开启，做好请求间隔、限流、异常重试；捕获429、验证码异常；第一版不启用自动爬虫
5. 版权约束：电子书MCP仅用于个人自用，不要实现批量下载、分发功能
6. 数据库操作全部走 ORM；不写裸SQL，避免注入风险
7. 改动架构、新增大模块前，先向我确认方案，不要直接重写现有结构
8. 所有接口返回结构化JSON；错误信息友好，日志分级输出
9. 开发顺序：优先落地首页仪表盘；再打通科研Zotero+feed RSS最小闭环；再依次开发todo、学习路线、旅游地图、小红书上传解析模块
10. 自动备份脚本仅负责源码的git提交推送，不会上传数据库与隐私文件

## 常用本地开发命令
```bash
# 安装依赖（uv）
uv sync
# 本地启动后端开发服务
uvicorn src.api.main:app --reload
# 运行单元测试
pytest tests/ -v
# 格式化代码
ruff format src/
# lint检查
ruff check src/
