# Changelog — Anima 随机提示词生成器

> 更新日志区间：`b0e72ae`(上次 release) → `HEAD`。最新版本：v2.1.0。

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
