# Changelog — Anima 随机提示词生成器

> 更新日志区间：`95b173e`(v3.3.1) → `HEAD`。最新版本：v3.3.2。

## v3.3.2 (当前发布候选)

基于 v3.3.1 的高级页**章节化 + 全汉化**重构。

### 高级页左侧章节导航

- 高级页改为 **左章节列表 + 右分页**（QListWidget + QStackedWidget），12 个逻辑章节：
  基础设置 / 抽样数量 / 子类配额 / 反趋同词配额 / 生成侧重点 / 多角色 / r18 控制 /
  API 参数 / 额外要求池 / 角色池 / 类别白名单 / 创意锚点池
- 每章独立滚动区（QScrollArea），切换章节即时跳转，不再滚动一个超长页面
- 章节内顶层键（如 sample_counts）作为可折叠小节，中文标题

### 全配置汉化

- 新增 `gui_qt/i18n.py`：章节分组 + 字段汉化映射（min→最少、max→最多、enabled→启用、
  probability→出现概率、weight→权重 等 90+ 项）+ 枚举值汉化（none→关闭、fixed→固定出现、
  probabilistic→概率出现、weighted→加权出现）
- **所有子配置均显示中文名**；英文配置键名 + yaml 注释一起放进**悬浮 tooltip**
  （悬停显示"配置键：xxx.yyy + 说明"）
- 枚举下拉显示中文标签，收集时自动还原英文值（reasoning_effort：关闭/低/中/高 → none/low/…）
- 章节标题、顶层键标题全部汉化（内容分级上限 / 抽样数量 / 子类配额 等）

### 验证

- 12 章节切换正常，每章滚动区 811x601 填充页面
- 字段收集结构正确（min_tags=40、deepseek 完整、修改后还原）
- 预设保存/切换/锚点懒加载/深色/缩放全通过
- Qt self-test 退出码 0；51 单元测试全过

## v3.3.1 (当前发布候选)

基于 v3.3.0 的 UX Review 修复（PySide6 版）。

### 布局 / 使用体验修复

- **高级页长键名标签截断**：`min_r18_tags_per_sample` / `tag_count_bonus` 等长键名原固定
  160px 被截断 → `_make_label` 自适应宽度（按文本宽 + 余量，最长 280px），超长自动省略号
  并 tooltip 显示全名
- **API 页说明文字被裁剪**：`支持任意 OpenAI 兼容接口…` 说明与 `例：DeepSeek…` 提示
  原 wordWrap 后高度不足 / 未换行 → 设置 wordWrap + minimumHeight，完整显示
- **窗口缩小时高级页滚动区塌缩**：缩小窗口后 QScrollArea 内容区被 minimumSizeHint
  撑爆 → `adv_inner.setMinimumSize(0, 0)`，任意窗口尺寸滚动区正常
- **生成页底部 272px 空白**：左侧参数区下方大量留白 → 额外要求文本框改为填充剩余空间
  （70px → 333px，写长要求更舒服），按钮/进度条贴底，留白 272px → 9px
- **验证**：5 Tab 无元素重叠（几何相交检测 0 处）；深色模式全控件配色一致（无白底残留）；
  900x640 最小窗口下所有 tab 尺寸正常

## v3.3.0 (当前发布候选)

基于 v3.2.1 的增量：**UI 框架迁移 tkinter → PySide6（Qt）**。

### 框架迁移

- **PySide6（Qt）重写 GUI**：`prompt/random_generator/gui_qt/`（theme.py / tooltip.py / forms.py / app.py），
  入口 `anima_gui_qt.py`；功能与 tkinter 版**全等价**：生成 / API / 高级 / 配置 / 日志 5 Tab、
  动态配置表单 + 悬浮帮助、多预设管理、深色/浅色主题、断点续存、预览复制
- **性能大幅提升**：Qt 原生控件 + 懒加载折叠，主窗口构建 **0.21s**（tkinter 版 1.1s），
  切 tab 即时；滚动流畅（QScrollArea）
- **主题**：Qt 样式表（QSS）浅色/深色，跟随系统（Windows 注册表探测），即时切换并记住
- **Tooltip**：Qt 原生 QToolTip（支持富文本 + 自动定位），悬停 0.4s 显示
- **打包**：`build_exe_qt.py` + `anima_gui_qt.spec`，PySide6 单文件 exe 约 **82 MB**（Qt 库大）
- **移除 tkinter 版**：`anima_gui.py` / `anima_gui.spec` / `build_exe.py` /
  `gui_app.py` / `gui_forms.py` 已删除（git 历史可回退）；共享逻辑
  （`gui_engine.py` / `config_presets.py` / `config_merge.py` / `yaml_comments.py`）保留

### 验证

- 无头 self-test：资源加载 / 预览 / 帮助 100% 覆盖 / Qt 表单构建+收集全通过
- 主窗口无头实例化：5 Tab / 深色主题 / 预设列表 / 表单 21 字段（懒加载）
- 预设 CRUD / 切换重建 / 配置收集保存 / 锚点懒加载展开全通过
- exe self-test 退出码 0，GUI 启动正常；51 项单元测试全过

## v3.2.1 (当前发布候选)

基于 v3.2.0 的修复：**悬浮帮助真实生效**、**API 页 OpenAI 兼容泛化**、**深色模式可见**、**启动/切换/滚动性能优化**。

### 悬浮帮助（Tooltip）修复

- **根因**：ttkbootstrap 2.2.2 **无 `tooltip` 模块**，原代码 import 失败后走了空兜底，悬浮完全无反应
- **修复**：自实现 `SimpleToolTip`（悬停 0.4s 显示置顶气泡，移开/点击消失，自动避让屏幕边缘），
  `_tooltip()` 优先用 ttkbootstrap 自带、缺失时用自实现；357 个配置字段 + 锚点条目全部可悬浮查看说明

### API 设置页 OpenAI 兼容泛化

- 标题与说明改为"API 设置（OpenAI 兼容格式）"，支持任意 OpenAI 兼容接口
  （DeepSeek / Moonshot / OpenRouter / 本地 vLLM 等）
- 模型改为可编辑下拉（deepseek-chat / gpt-4o / moonshot-v1 / qwen / glm 等常用模型）
- 接口地址附示例说明；思考模式标注 reasonng_effort（不支持的平台自动忽略）

### 深色模式可见性修复

- **根因**：底部栏与状态栏分别 pack 在窗口 BOTTOM，notebook 请求尺寸过大（各 tab 内容撑大）
  把底部栏挤出可视区域（mapped=0）
- **修复**：状态栏 + 外观切换合并到同一底部容器，notebook 最后 pack；
  实测真实 mainloop 下外观下拉可见（mapped=1），深色/浅色/跟随系统即时切换

### 性能优化（启动 3.4s → 1.1s，切 tab 211ms → 124ms）

- **懒加载折叠**：默认折叠的危险区/大数据区（子类配额、r18 主题、额外要求池、角色池、
  白名单池、词配额、r18 专用配额、sample_counts）与**创意锚点池（78 条）**折叠时不构建控件，
  首次展开才构建（`CollapsibleSection.build_callback`）
- 初始字段 357 → 21；GUI 启动 3.4s → 1.1s；切 tab 211ms → 124ms
- **滚轮滚动**：高级页 Canvas 绑定 `<MouseWheel>`（Windows 默认不响应滚轮），滚动流畅

## v3.2.0 (当前发布候选)

基于 v3.1.0 的增量：**多配置预设**（保存/切换/导入/导出）、**深色模式**、**全字段悬停帮助**。

### 配置预设（「配置」Tab 新增）

- **多预设管理**：每套预设 = 完整生成配置（generation_config 覆盖）+ 创意锚点覆盖；
  支持「新建 / 复制 / 重命名 / 删除 / 切换 / 保存当前到预设」
- **切换语义**：切换预设时若当前有未保存修改，询问是否先保存到当前预设；加载目标
  预设后**重建高级页表单**并同步生成页参数（`_rebuild_adv_form_from_profile`）
- **导入/导出**：导出为可分享 `.yaml`（含 gen + anchors）；导入校验结构后自动处理重名
  （追加 "(2)" 后缀）；预设存储于 `%APPDATA%\AnimaPromptGenerator\profiles.json`
- **激活即生效**：激活预设写入 `user_config.yaml`（引擎合并源），生成即用当前预设；
  「高级」页保存设置同步到当前预设（`config_presets.py`）
- 旧版 `user_config.yaml` 自动迁移为「默认」预设的非空版本

### 深色模式

- 窗口底部「外观」下拉：浅色（flatly）/ 深色（superhero）/ 跟随系统（Windows 注册表探测）
- 切换时同步 ttkbootstrap 主题 + tk 原生控件（Text/Canvas/Listbox）配色；
  选择记住到 settings.json，下次启动应用

### 全字段悬停帮助（100% 覆盖）

- `yaml_comments.semantic_help`：为无注释字段按路径/键名语义生成兜底说明
  （min/max 配额、r18 主题参数、词配额、抽样数量、focus 权重、锚点字段、通用键名等）
- 357 个叶子字段帮助覆盖率 **37 注释 + 320 语义 = 100%**；ListEditor 内部字段（锚点条目）
  同样接入语义帮助

## v3.0.0 (当前发布候选)

基于 v2.1.0 的增量：**桌面图形界面（GUI）单文件 exe 版**，面向不熟悉 Python / 配置文件的使用者。

### 桌面 GUI（新）

- 新增 `anima_gui.py`（入口）+ `prompt/random_generator/gui_app.py`（界面）+ `gui_engine.py`（引擎层）
- **中文 4-Tab 界面**（ttkbootstrap，flatly 主题）：
  - **生成**：数量、内容分级（general/pg12/r15/r18/r18g，首次切 r18/r18g 弹成人确认）、
    随机/固定种子、主题提示、额外要求、强制/排除 tag、输出目录/文件名、
    创意锚点/多角色开关、预览样本、开始/停止、实时进度条、结果列表（双击看全文 + 复制）
  - **API 设置**：API Key（密码框 + 显示切换 + "记住"勾选，保存到 `%APPDATA%\AnimaPromptGenerator\settings.json`，
    绝不写入项目）、接口地址、模型、Temperature、超时、思考模式、测试连接
  - **高级**：min/max tags、并发数、最大输出 token、解析重试、额外要求池开关、子类配额只读摘要
  - **日志/输出**：滚动日志、打开输出文件夹
- **大批量生成**：多线程 + 逐条落盘 + 断点续存（同一输出文件自动跳过已生成条数，停止后重开不重复）、
  可取消（已生成结果不丢失）
- **评级感知资源加载**：按 max_rating 预过滤知识库并按评级缓存，切换 r18 自动重建
- **引擎层复用完整生成链路**：抽样 → 组装 → 渲染 → DeepSeek → 后处理 → 审计落盘，与 CLI 行为一致

### 高级页完整配置编辑（新增）

- **全量配置可视化**：`generation_config.yaml` 与 `creative_anchors.yaml` 的全部配置项
  自动加载并按数据类型渲染控件——int→步进框、float→步进框(0.1)、bool→开关、
  短文本→输入框、长文本/多行→文本框、枚举(reasoning_effort/topic mode)→下拉、
  标量列表/对象列表→可增删编辑器、深层嵌套→递归展开；78 个创意锚点逐条可编辑
- **帮助信息零维护**：`yaml_comments.py` 直接从 yaml 注释提取每项的说明文本，
  悬停控件即显示"配置内容 + 修改效果"（与 yaml 同步，无需单独维护说明表）
- **分类折叠**：`gui_forms.py` 的 CollapsibleSection——基础区默认展开，
  危险区（r18 主题控制 / extra_requirements_pool / 角色池 / 白名单池 / r18 专用
  配额 / default_word_quota）默认折叠；支持「全部展开/折叠」
- **保存设置**：`config_merge.py` 深合并 + diff——只写与默认**不同**的键到
  `%APPDATA%\AnimaPromptGenerator\user_config.yaml`（用户目录，exe 打包版 yaml 只读，
  修改经用户目录生效）；「恢复默认」删除该文件；锚点区仅当确实修改时才落盘
- **引擎合并**：`gui_engine._load_generation_config` 读默认 + 用户覆盖；
  `load_resources` 注入用户锚点覆盖；保存后自动失效引擎缓存，下次生成即用新配置

### 打包

- `build_exe.py`：一键打包单文件 exe（自动装 PyInstaller/ttkbootstrap、清理、校验产物）
- `anima_gui.spec`：仅打包运行时资源（知识库 v1 + 2 个黑名单 csv + 模板/配置/角色池，
  剔除 source/ 下 100MB+ 非运行文件），产物约 **46 MB**
- exe 内置 `--self-test`（加载资源 + 预览，写结果文件）用于交付前完整性自检
- 打包机需 PyInstaller + ttkbootstrap；**exe 用户无需安装任何东西**

### 验证

- 引擎 dry-run（资源加载 8s / 知识库 38681 条 / 预览渲染 9823 字符）通过
- GUI 实例化 / 控件构建 / 设置持久化 / 评级切换重建 / 队列联动全部通过
- exe self-test（PyInstaller 打包环境）通过：资源完整、预览正常、退出码 0
- 单测 51 项全通过（修复既有 `test_reads_min_r18_tags_and_instructions` 的返回元组解包 bug）

## v2.1.0 (当前发布候选)

基于 v2.0.1 的增量：提示词模板 V2（规则优先级与角色硬特征）、审计溯源扩展、概率性创作火花。

### 提示词模板 V2（规则优先级与角色硬特征）

- **RULE PRIORITY（P0–P4）置顶**：P0 安全 → P1 角色硬特征 → P2 外部控制 → P3 结构 → P4 创意；消除"几十条 MUST 平铺、模型自行裁决冲突"导致的批量漂移
- **CHARACTER_TRAITS / INPUT TYPES**：角色核心（CHARACTER_CORE）必须保留；`loli` 作为角色/年龄描述词全局豁免（`shota`/非自愿/胁迫等其余禁令不变）；输入按 CHARACTER_CORE / FORCED / FORBIDDEN / CREATIVE_ANCHOR / SAMPLED 打标签，优先级由标签而非语气推断
- **CREATIVE COMPLETION**：sampled 由"theme seeds"改为**候选池**（可丢弃多数），允许有限新增 tag 仅用于语义/构图/关系补全
- 场景描述句统一 **2–4 句**（消除原先 system 1–4 与 user 1–2 的矛盾）；新增**温和构图多样性**一条
- **CREATIVE SPARK**：约 40% 样本概率注入 1 个惊喜点指令，置于输入**尾部**以保持前缀缓存命中

### 审计 / 溯源（schema_version 1 → 2）

- 新增 `eval_input`：渲染后 system/user 原文 + `template_version`（system_prompt.md + user_prompt.jinja 内容指纹）
- 新增 `model_raw_output`：后处理前模型原始输出
- `params` 补 `forced_tags` / `forbidden_tags`；`creative_spark` 标记
- 旧 `schema_version: 1` 记录仍可读

### 运行与数据

- 运行时抽样 tag 合计 123 个/条（10 类），最终 prompt 保持 40–60 tags 硬约束
- 多线程抽样（每 worker 独立 RNG，线程安全）+ 角色池文件缓存（4.7MB JSON 每样本只读一次）

### 验证

- dry-run / 真实生成（mimo-v2.5, thinking none, 固定角色 deepseek 50 条）全通过；特征保留率 deepseek/cetacean tail 50/50、loli 49/50
- 单测 51 项通过 50（1 项既有无关失败：`test_reads_min_r18_tags_and_instructions` 涉及 cli `_build_config` 合并，与本次改动无关）

## v2.0.1 (2026-08-22)

基于 v2.0.0 的增量：提示词引导去套路化、缓存/运行优化、数据入库与仓库精简。

### 提示词与生成质量

- **场景句引导去套路化**：移除 "lighting intent / atmosphere / camera position" 等诱导词与 `gentle breeze / golden light / misty shrine` 等点名示例，改为引导"具体可见物象与布局"；`default word quota` 点名词笼统化（`f550896`）
- **sampled 分歧点后置**：固定指令前置 + 变量集中于尾部 SOURCE MATERIAL 段，DeepSeek 前缀缓存稳定命中 64% → 73%（单条最高 86.5%），生成质量不劣化（`0127fe2`）
- **NL 场景句具体意象趋同治理**：完成 mimo/ox 批次意象归因（猫/花瓣/雾多为 LLM 自创、月/云/雪/灯笼多为抽样），确定"抽样频率帽 + LLM 引导"分治方向

### 数据与仓库

- **原始标签 CSV 入库**：`danbooru_e261_updated.csv` 移入 `知识库/` 并随库分发——`git clone` 后即可直接运行 `build_curated_tags`，`TAG_SOURCE_FILE` 同步指向新路径（`bee386f`、`cb85798`）
- **移除推送中的审计与文档**：分类审计 `map_*.txt`（188 个）与 `反趋同改造方案.md` 移出版本库、归档至本地 `archive/`，README 同步（`93102ac`）
- `.gitignore` 补 `openrouter/` 保护（含 key 的本地 API 工具）

### 验证

- 全链路验证通过：模块导入 / 知识库加载（10 类、r15 预过滤 38681）/ 角色池 8940 / 锚点 75 / `generate --dry-run` exit 0
- 仓库推送目录精简至 50 个文件，无冗余、无 key、无临时产物

## v2.0.0 (2026-08-19)

本轮为一次较大的分类体系 + 生成质量改造：完成知识库人工细粒度分类、content 两档制（排除/性行为与 r18 评级拆分）、画面美感约束与大规模趋同收敛、提示词结构优化，并清理了仓库中的临时脚本与测试产物。

### 新增功能

- **人工细粒度分类与"分类即排除"机制**：知识库 v1 越界内容改写为 `排除/<子类>` 整类丢弃（任何模式含 r18 均不可见），消除正则误判（`78a9845`）
- **`排除/性行为` 两档拆分**：拆为"直接暴露"（显性性器官/体液词，维持硬排除）与"擦边软色情"（`表情动作/擦边`、`物品/擦边`、`人物/擦边` 子类，低配额入池，r15 可偶尔出现）（`38ab3bd`）
- **r18 评级两档拆分**：995 条 rating=r18 的 tag 细分——263 条擦边软色情降级 r15 入池，732 条直接暴露维持 r18（`e77d693`）
- **子类配额抽样**：每个内部类别按子类 min/max 配额控制出现频率；并收编全部"未列入配额表（unlisted）"子类，消除高频趋同放大器（`d9b6ddc`、`fc92fa5`）
- **创意锚点机制**：78 个高概念设定打破画面趋同 + 保留校验与丢失自动重试（`e467f53`、`d01b21a`）
- **逐条审计日志** `audit_log.jsonl` + 指纹算法共享模块 `prompt_hash.py`（`c33d8b4`、`d7ddb1d`）

### 生成质量与画面美化

- **画面美感约束**（postprocess）：排版/分镜类词剔除、风格画面词每样本限 1、表情词族互斥（同族 1 个 + 全样本 ≤3）、现实场所词每画面限 1（`cbac159`）；锚点池支持 `enabled: false` 禁用排版类设定
- **趋同收敛**：构图类子类默认 `max:0`（无显式构图）、灰底滤镜等风格化背景排除、高频姿态池（`表情动作/其他动作`）限流、背景样式类降 max（`fc92fa5`）；system prompt 与 user prompt 双禁构图法则词 + postprocess 兜底剔除（`c526b2d`）
- **输出单行化与分隔优化**：`version_1` 单行输出；tag 区与自然语言句间逗号分隔、自然语言句间仅空格（句号天然分隔）（`027d12f`、`a6d7930`）
- **sampled tags 位置**：固定采用"放于用户提示词末尾（tail）"——直接对比 head/tail 后，tail 画面质量更聚焦、且 DeepSeek 前缀缓存命中更高（`8c25fed`）

### 知识库补判

- 外貌/画面质感/服装款式三池全量细分类（10213 条，`a2cdd95`）
- 镜头/背景/环境/表情/姿势动作（3317 条，`2f4db67`）与物品池全量（6144 条，`e8bc5f6`）补判
- 正则漏杀假阴性排除项补判（47 条，`a40a8ec`）

### 配置与文档

- README 补充分类两档制/擦边子类/子类配额纪律/美感约束/趋同收敛与维护工具说明（`7293b81`）
- `.gitignore` 屏蔽 `anima_prompt_develop/`、`*.env`、`api_profiles/`、`opencode/` 等敏感目录，API key 仅允许命令行传入（`740e799`、`db03159`）
- 反趋同抽样配置分析修复（P0/P1 四项，`717baf7`）

### 其他 / 清理

- 一次性脚本（`apply_r18_tier` / `merge_r18_classify` / 各 `export_*` / `clean_*` 等）与测试产物移动至本地 `archive/`（忽略，不入库），保留正式工具 `apply_unclassified_maps` / `build_*` 与 `map_*.txt` 审计映射（`d8f8bb9`）

### 完整提交列表

`git log --oneline b0e72ae..HEAD` 共 40 个提交，详见仓库历史：
`8c25fed cff0672 d5779d1 ea04d65 c526b2d a6d7930 d8f8bb9 027d12f 7293b81 fc92fa5 cbac159 e77d693 38ab3bd f5efd2f 7662f6a e8bc5f6 2f4db67 a40a8ec 78a9845 fc81fb4 a2cdd95 d7ddb1d c33d8b4 717baf7 d9b6ddc d01b21a e467f53 db03159 4206420 b82769d fd7cf9d d054166 740e799`
