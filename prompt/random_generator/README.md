# DeepSeek 随机提示词生成器

本模块从项目知识库中按类别随机抽样 tag，作为主题种子调用 DeepSeek API，生成并后处理符合 Anima 模型习惯的单版本提示词（`version_1`；`version_2` 默认关闭——历史 v2 只是 v1 的复制，完全相同无生成价值）。

## 简介

生成器的工作目标：

1. 从 `source/danbooru_e261_updated.csv` 加载已分类的 danbooru tag 知识库。
2. 按内部类别抽样，并做冲突消解、噪音过滤、年龄分级过滤（噪音在**输入侧**排除，见 `config.NOISE_META_TAGS`）。
3. 将抽样 tag 渲染为结构化的用户提示词，调用 DeepSeek API。
4. 对 API 返回结果进行后处理：画师黑名单过滤、禁词替换、冲突消解、来源校验、r18 占位符还原。
5. 输出 JSONL，每条记录包含忠实还原版与震撼美化版两个 prompt，以及完整的处理日志。

模块默认面向"可爱少女向"二次元插画，已内置大量过滤规则，会自动丢弃男性、成熟女性、纯兽人、深肤/非人肤色、暴力血腥、元数据噪声等不适合的 tag。

**分类体系（分类即排除 + 两档制）**：

- `知识库/v1` 已逐条人工细粒度分类，越界内容改写为 `排除/<子类>` 整类丢弃（含 r18 模式）；
- `排除/性行为` 与 rating=r18 的 tag 均按两档拆分：**擦边软色情**（`表情动作/擦边`/`物品/擦边`/`人物/擦边`，
  低配额入池，r15 可偶尔出现）与**直接暴露**（显性性器官/体液词，维持硬排除或 r18）；
- 出现频率由 `subcategory_quotas` 子类配额控制，**未列入配额表的子类=不设限（趋同放大器），新增子类必须列入**；
- 输出侧 `_apply_aesthetic_constraints`（postprocess）：排版/分镜词剔除、风格词≤1、表情词族互斥≤3、
  现实场所词≤1；锚点池 `creative_anchors.yaml` 支持 `enabled: false` 禁用排版类设定；
- 构图类子类（构图法则/构图氛围）默认 `max:0`（无显式构图），高频姿态池/背景样式类降 max——
  目标为每天 1200 张量级不产生"既视感"（500 批模拟：构图词 0、高频姿态 0.8%、灰底 0）。

通过 `--max-rating r18` / `r18g` 可开启成人内容模式，支持 r18 主题控制（17 类主题独立开关/概率/权重/联动）、单人场景主题限制（`solo`）、r18 内容占比提示（`r18_focus_weights`）与每样本最少 r18 tag 数（`min_r18_tags_per_sample`），相关配置详见下文与 `generation_config.yaml`。

## 快速开始

### 1. 安装依赖

在项目根目录执行：

```bash
pip install -r prompt/random_generator/requirements.txt
```

依赖：`openai>=1.0`、`jinja2`、`pyyaml`。

### 2. 配置环境变量

复制示例环境文件并填写真实 API Key：

```bash
cp prompt/random_generator/example.env .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-v4-flash
```

加载环境变量（PowerShell）：

```powershell
Get-Content .env | ForEach-Object { if ($_ -match '^(\w+)=(.*)$') { [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2]) } }
```

或在 Bash 中：

```bash
export $(grep -v '^#' .env | xargs)
```

### 3. 首次 `--dry-run` 验证

不调用 API，仅检查抽样与提示词渲染是否正常：

```bash
python -m prompt.random_generator.cli generate --dry-run --seed 42
```

正常应输出抽样标签、冲突消解日志和渲染后的用户提示词，并以退出码 `0` 结束。

### 4. 实际生成

生成 5 条提示词并保存到默认输出文件：

```bash
python -m prompt.random_generator.cli generate --count 5
```

默认输出：`output/random_prompts.jsonl`。

## 运行方式

### 常用 CLI 命令示例

生成 5 条提示词并保存为 JSONL：

```bash
python -m prompt.random_generator.cli generate --count 5 --output output/prompts.jsonl
```

使用自定义配置与主题提示：

```bash
python -m prompt.random_generator.cli generate \
  --count 3 \
  --config prompt/random_generator/example_config.yaml \
  --theme-hint "雨中都市夜景，霓虹反光" \
  --output output/cyberpunk.jsonl
```

指定随机种子以获得可复现的抽样结果：

```bash
python -m prompt.random_generator.cli generate --count 3 --seed 42 --output output/seeded.jsonl
```

重建旧版 curated pools（兼容性维护）：

```bash
python -m prompt.random_generator.cli generate --rebuild-pools --dry-run
```

从 CSV 重新构建带年龄分级的 `curated_tags.yaml`：

```bash
python -m prompt.random_generator.cli generate --rebuild-curated --dry-run
```

### 项目根目录入口

项目根目录提供了快捷入口 `run_generator.py`，功能与 `python -m prompt.random_generator.cli` 完全一致。由于当前 CLI 只有 `generate` 一个子命令，快捷入口允许省略 `generate`：

```bash
python run_generator.py --count 1 --dry-run --seed 42
```

也支持显式写出子命令：

```bash
python run_generator.py generate --count 1 --dry-run --seed 42
```

所有 `generate` 子命令的参数均可直接透传。

### 完整 CLI 参数表

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `generate` | 子命令 | - | 唯一子命令，用于生成随机提示词 |
| `--count` | `int` | `1` | 生成提示词的数量 |
| `--output` | `str` | `None` | 输出文件路径；未指定时使用 `<output_dir>/random_prompts.jsonl` |
| `--v2-only` | 标志 | `False` | 已废弃：v2 已关闭（v1/v2 完全相同无生成价值），参数不再生效 |
| `--v2-enhance` | 标志 | `False` | 对 v1 额外调用一次 API，按 anima V2 规则精修为震撼美化版（`version_2`）。实测不建议使用（2026-08-09 r15/r18 各 8 条：输出 tag 数 87~89 超 75 上限、自然语言句变 30+ 词长清单体、未过 postprocess 校验、成本翻倍；r15/r18 行为一致） |
| `--config` | `str` | `None` | YAML 配置文件路径；与默认配置合并，同名项以自定义配置为准 |
| `--seed` | `int` | `None` | 随机种子，用于可复现抽样 |
| `--theme-hint` | `str` | `""` | 场景主题提示，直接传递给 DeepSeek |
| `--dry-run` | 标志 | `False` | 不调用 API，仅打印抽样与渲染结果到 stdout |
| `--rebuild-pools` | 标志 | `False` | 重新构建旧版 curated pools 后再生成 |
| `--rebuild-curated` | 标志 | `False` | 从 CSV 重新构建 `curated_tags.yaml` 后再生成 |
| `--max-rating` | `str` | `None` | 允许抽样的最大年龄分级；可选 `general`、`pg12`、`r15`、`r18`、`r18g` |
| `--min-tags` | `int` | `None` | 最终提示词最少 tag 数量 |
| `--max-tags` | `int` | `None` | 最终提示词最多 tag 数量 |
| `--subject-control` | `str` | `""` | 外部主题/主体控制文本，直接传递给用户模板 |
| `--forced-tags` | `str` | `""` | 强制包含的 tag，逗号分隔 |
| `--forbidden-tags` | `str` | `""` | 强制排除的 tag，逗号分隔 |
| `--extra-requirements` | `str` | `None` | 用户自定义额外要求，覆盖配置文件中的 `extra_requirements` |
| `--character-json` | `str` | `None` | 自定义角色池 JSON 文件路径；格式与 `character_pool.json` 相同，启用后替代默认角色池 |
| `--workers` | `int` | `4` | 并发调用 DeepSeek API 的 worker 数量；仅在真实生成时生效 |

### `--dry-run` 与真实 API 调用的区别

| 行为 | `--dry-run` | 真实生成 |
|------|-------------|----------|
| 调用 DeepSeek API | 否 | 是 |
| 输出位置 | stdout | 指定 JSONL 文件 |
| 后处理过滤 | 否 | 是 |
| 保存记录 | 否 | 是 |
| 用途 | 调试抽样与提示词模板 | 批量生产提示词 |

## 配置方式与配置项解释

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（**必填**） | - |
| `DEEPSEEK_API_BASE` | DeepSeek API 基础地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 使用的模型名称 | `deepseek-chat` |

优先级：显式传入参数 > 环境变量 > `config.py` 默认值。

### 默认配置文件

默认配置文件位置：

```text
prompt/random_generator/generation_config.yaml
```

完整默认内容：

```yaml
# 允许抽样的最大年龄分级（general / pg12 / r15 / r18 / r18g）
max_rating: r15

# r18 模式下每个样本至少抽到的 r18 评级 tag 数量（0 表示不强制；仅 max_rating=r18 时生效）
min_r18_tags_per_sample: 15

# r18 模式下注入到 LLM 用户提示词的自定义指令文本（可多行，原样注入）
r18_instructions: ""

# 每个内部类别的抽样数量
sample_counts:
  count_gender: 2
  appearance: 20
  clothing_state: 20
  pose_action_sex: 20
  expression_reaction: 20
  camera_shot: 5
  scene_environment: 20
  detail_mood: 9

# r18 模式专用抽样数量（仅 r18/r18g 覆盖 sample_counts）
r18_sample_counts:
  count_gender: 2
  appearance: 16
  clothing_state: 15
  pose_action_sex: 16
  expression_reaction: 15
  camera_shot: 5
  scene_environment: 14
  detail_mood: 6

# r18 标签主题控制（仅 r18/r18g 生效；17 类主题独立开关/模式/数量/权重/联动）
r18_topic_control:
  enabled: true
  topics:
    nudity_exposure: {mode: fixed, count: 1}
    reactions: {mode: fixed, count: 2}
    body_features: {mode: weighted, weight: 2, count: 2}
    bondage: {mode: probabilistic, probability: 0.3, count: 3, linked_topics: [clothing_props], link_probability: 0.8}
    oral: {mode: probabilistic, probability: 0.3, count: 2, linked_topics: [cum], link_probability: 0.5}
    # ...（完整列表见 generation_config.yaml 与 r18_topics.yaml）
  solo:                          # 单人场景主题限制
    enabled: true
    disabled_topics: [oral, penetration, positions]

# 最终提示词长度约束（tag 数量）
min_tags: 40
max_tags: 60

# 生成侧重点权重（百分比）
focus_weights:
  character: 40
  background: 40
  other: 20

# r18 模式专用占比（仅 r18/r18g 覆盖 focus_weights）
r18_focus_weights:
  character: 40
  background: 20
  r18: 20
  other: 20

# 多角色场景自动调整（命中 2girls 等标记时生效）
multi_character:
  tag_count_bonus: 30
  focus_character_bonus: 5

# DeepSeek API 调用参数
deepseek:
  temperature: 0.7
  max_tokens: 1000
  reasoning_effort: "none"
  timeout: 120
  max_parse_retries: 2

# 默认输出目录
output_dir: output

# 用户自定义额外要求（字符串）
extra_requirements: |
  画面要体现出可爱的感觉。

# 额外要求池化配置
extra_requirements_pool:
  enabled: true
  mutex_groups:
    - items:
        - text: "画面要体现出可爱的感觉。"
          weight: 5
        - text: "画面要体现出唯美的感觉。"
          weight: 10
  optional_items:
    - text: "加入随风飘落的樱花花瓣。"
      probability: 0.25

# Excel / JSON 角色池配置
character_pool:
  enabled: true
  file: null
  prefer_same_ip_for_multiple: true
  use_core_appearance: true
  use_core_clothing_probability: 0.8
  series_index_file: null

# 白名单角色池（旧版）
character_whitelist:
  enabled: false
  pool: []

# 通用类别白名单池
category_whitelists:
  enabled: false
  pools:
    count_gender: []
    appearance: []
    clothing_state: []
    pose_action_sex: []
    expression_reaction: []
    camera_shot: []
    scene_environment: []
    detail_mood: []
    character_series: []
```

### 自定义配置文件加载优先级

1. 命令行 `--config <path>`（最高优先级）
2. `prompt/random_generator/generation_config.yaml`（默认配置）
3. `config.py` 中的硬编码默认值（最低优先级）

即：命令行 `--config` > 默认 `generation_config.yaml` > `config.py` 默认值。

### 配置项逐项解释

#### `max_rating`

- **含义**：允许抽样的最大年龄分级。
- **取值范围**：`general`、`pg12`、`r15`、`r18`、`r18g`，严格程度递增。
- **默认值**：`r15`。
- **调整建议**：若需要更保守的生成结果，设为 `pg12` 或 `general`；若需要更开放的成人内容，设为 `r18`（需确保 API 与合规策略允许）。设为 `r18`/`r18g` 时，下列 r18 相关配置才会生效。

#### `min_r18_tags_per_sample`

- **含义**：r18 模式下每个样本至少抽到的 r18 评级 tag 数量（仅 `max_rating=r18` 时生效）。
- **默认值**：`15`（可通过配置文件调整）。
- **说明**：补充抽样仍会通过全部清洗规则，不会绕过男性/扶她/福瑞/r18g 等禁用类别过滤；置 `0` 表示不强制补充。

#### `r18_instructions`

- **含义**：r18 模式下注入到 LLM 用户提示词的自定义指令文本（可多行，原样注入）。
- **默认值**：空字符串（不注入）。
- **说明**：仅提供注入机制，不会解除系统提示词中的分级与清洗规则。

#### `r18_sample_counts`

- **含义**：r18 模式专用抽样数量，仅 `max_rating` 为 `r18`/`r18g` 时覆盖 `sample_counts`。
- **作用**：减少每样本输入 tag 总量（约 120 → 约 84），降低 LLM 丢弃压力，避免 r18 补充的成人 tag 因数量过大被优先丢弃。非 r18 模式完全不受影响。

#### `r18_topic_control`

- **含义**：r18 标签主题控制，根据 `r18_topics.yaml` 的 17 个主题逐类调节出现概率。
- **每主题支持的字段**：
  - `enabled`：是否参与（`false` = 主题下全部 tag 在主抽样与 r18 补充中都不出现）；
  - `mode`：`fixed`（固定出现）/ `probabilistic`（按 `probability` 出现）/ `weighted`（按 `weight` 调节权重）；
  - `count`：目标 tag 数量（主题类设 `count>1` 使主题集中出现）；
  - `probability`：`probabilistic` 模式的出现概率（0-1）；
  - `weight`：加权模式的抽样权重（默认 1）；
  - `linked_topics` / `link_probability`：本主题激活时以该概率同时激活联动主题。
- **`solo` 单人场景限制**：`enabled: true` 时，单人画面（1girl/1boy 等非多人标记）强制不激活 `disabled_topics` 列表中的主题（默认 `[oral, penetration, positions]`），避免单人画面出现需要双人配合的动作；多人场景（2girls 等）不受影响。

#### `sample_counts`

- **含义**：每个内部类别在每次生成中抽样的 tag 数量。
- **默认值**：总计 116 条。
- **调整建议**：
  - 增加 `appearance`、`detail_mood` 可让人物与画面更丰富。
  - 减少 `pose_action_sex` 可降低动作/体位相关 tag 的密度。
  - 总计建议保持在 50 以上，以便 LLM 丢弃不适合 tag 后仍能满足 `min_tags`。

#### `min_tags` / `max_tags`

- **含义**：最终提示词应包含的 tag 数量区间。
- **默认值**：`min_tags=40`，`max_tags=60`。
- **调整建议**：
  - 若希望 prompt 更简短，可同时调低两者（需同步减少 `sample_counts`）。
  - 若希望更详细，可提高上限并增加抽样数量。

#### `focus_weights`

- **含义**：提示 LLM 在最终 prompt 中各类描述的占比。
- **默认值**：`character: 40`、`background: 40`、`other: 20`。
- **调整建议**：
  - 提高 `character` 可让人物细节更突出。
  - 提高 `background` 可让场景、氛围、镜头更突出。
  - 三个值之和不必严格等于 100，仅作为相对权重参考。

#### `r18_focus_weights`

- **含义**：r18 模式专用占比，仅 `max_rating` 为 `r18`/`r18g` 时覆盖 `focus_weights`。
- **默认值**：`character: 40`、`background: 20`、`r18: 20`、`other: 20`。
- **说明**：仅提示 LLM 调整最终 prompt 中 r18 内容与背景的占比，不改变任何类别的抽样数量。

#### `multi_character`

- **含义**：多角色场景（如 2girls）命中时的自动调整。
- **字段**：
  - `tag_count_bonus`：`min_tags` 与 `max_tags` 各增加该值（默认 `20`）；
  - `focus_character_bonus`：`character` 占比增加该值（百分比），从 `background` 与 `other` 按比例扣减。
- **说明**：多角色画面需要更多 tag 描述每个角色，自动放宽长度约束并提升角色占比。

#### `deepseek`

- **含义**：DeepSeek API 调用参数。
- **默认值**：`temperature: 0.7`、`max_tokens: 1000`、`reasoning_effort: "none"`、`timeout: 120`、`max_parse_retries: 2`。
- **调整建议**：
  - `temperature` 越低，生成结果越稳定；越高越多样。
  - `reasoning_effort: "none"` 关闭推理（输出更快、不占 `max_tokens`、更便宜）；开启 `"low"`/`"medium"`/`"high"` 会占用 `max_tokens`，需相应调大。
  - 若频繁遇到 JSON 截断，可提高 `max_tokens`。
  - `max_parse_retries` 控制空内容/JSON 异常时的重试次数。

#### `output_dir`

- **含义**：命令行未指定 `--output` 时的默认输出目录。
- **默认值**：`output`。

#### `extra_requirements` / `extra_requirements_pool`

- **`extra_requirements`**：字符串，每次生成原样注入 LLM 用户提示词。
- **`extra_requirements_pool`**：池化配置，启用后动态抽样额外要求。
  - `mutex_groups`：多个互斥列表，每个列表按 `weight` 抽取 **恰好一项**。
  - `optional_items`：可选项列表，每项按 `probability` 独立决定是否加入。
- **优先级**：`extra_requirements_pool.enabled: true` 时优先使用池化配置；命令行 `--extra-requirements` 可覆盖两者。

#### `character_pool`

- **含义**：Excel / 自定义 JSON 角色池配置。启用后，`character_series` 从角色池中抽样，替代知识库 v1 的二次元角色抽样。
- **关键字段**：
  - `file`：角色池 JSON 文件路径；`null` 表示使用默认 `character_pool.json`。
  - `prefer_same_ip_for_multiple`：多角色场景下优先从同一 `series_tag` 抽样。
  - `use_core_appearance`：是否向 LLM 注入 `core_appearance_tags`。
  - `use_core_clothing_probability`：使用角色核心服饰词的概率。
  - `series_index_file`：IP 索引路径；`null` 时自动使用 `<file_stem>_series_index.json`。
- **IP 权重**：IP 索引中的 `weight` 字段（默认 `10`）控制该作品被抽中的概率；重新构建缓存时会保留手动修改值。
- **命令行覆盖**：`--character-json <path>` 会强制启用角色池并替换为指定 JSON 文件，适合临时指定单个角色或自定义小角色池。

#### `character_whitelist`

- **含义**：旧版白名单角色池，指定固定角色列表。
- **建议**：迁移到 `category_whitelists.pools.character_series`。

#### `category_whitelists`

- **含义**：通用类别白名单池。启用后，对 `pools` 中非空的类别优先从对应池抽样，替代该类别原有的知识库 v1 抽样。
- **默认值**：`enabled: false`，所有类别的 `pools` 均为空列表。
- **调整建议**：
  - 适合需要固定某些类别候选集的场景，例如限定角色、服装、场景等。
  - 空池或未指定的类别保持原有知识库 v1 抽样逻辑。
  - `character_series` 池优先级高于旧的 `character_whitelist`。

## 运行流程

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│  source/danbooru_e261_updated.csv                                           │
│       │                                                                       │
│       ▼                                                                       │
│  load_tag_database ──▶ 按 8 个内部类别分组                                    │
│       │                                                                       │
│       ▼                                                                       │
│  sample_tags_by_category ──▶ 分类抽样 + 年龄分级过滤 + 噪声过滤               │
│       │                                                                       │
│       ▼                                                                       │
│  build_prompt_payload / resolve_conflicts ──▶ 冲突消解                        │
│       │                                                                       │
│       ▼                                                                       │
│  format_tags_for_llm ──▶ 按类别渲染为自然语言文本                             │
│       │                                                                       │
│       ▼                                                                       │
│  render_user_prompt ──▶ 填充 user_prompt.jinja 模板                           │
│       │                                                                       │
│       ▼                                                                       │
│  call_deepseek ──▶ DeepSeek API 生成 version_1 / reasoning                  │
│       │                                                                       │
│       ▼                                                                       │
│  postprocess ──▶ 画师过滤、禁词替换、冲突消解、来源校验                        │
│       │                                                                       │
│       ▼                                                                       │
│  JSONL 输出到 <output_dir>/random_prompts.jsonl                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 每个阶段的关键输入输出

| 阶段 | 关键输入 | 关键输出 |
|------|----------|----------|
| 源 CSV 加载 | `source/danbooru_e261_updated.csv` | `database: {category: [tag_item]}` |
| 分类抽样 | `sample_counts`、`max_rating`、`curated_tags.yaml` | `sampled_tags: {category: [tag_item]}` |
| 冲突消解 | `sampled_tags`、`CONFLICT_RULES` | `resolved_tags`、`conflict_log` |
| 提示词渲染 | `resolved_tags`、`min_tags`、`max_tags`、`theme_hint`、`focus_text` | 渲染后的用户提示词 |
| DeepSeek 生成 | 系统提示词 + 用户提示词 | `version_1`、`reasoning`、`raw` |
| 后处理过滤 | `artist_blacklist`、`database`、替代标签白名单 | `postprocess_log`、`unknown_tags` |
| JSONL 输出 | 处理后的记录列表 | 单行 JSON 文件 |

## 脚本/模块功能说明

本模块根目录保留核心运行模块与配置模板；辅助分析、检查与维护脚本统一放在 `tools/` 子目录中，避免根目录过于拥挤。

- **核心模块**：`cli.py`、`retrieval.py`、`assembler.py`、`client.py`、`postprocess.py`、`config.py`、`tag_classification_rules.py` 以及 `system_prompt.md`、`user_prompt.jinja`、`curated_tags.yaml`、`r18_topics.yaml`、`r18_euphemisms.yaml`、`semantic_exclude.yaml`、`generation_config.yaml` 等仍位于 `prompt/random_generator/` 根目录。
- **辅助脚本**：`build_character_pool.py`、`build_curated_pools.py`、`build_curated_tags.py`、`sort_character_pool.py` 位于 `prompt/random_generator/tools/` 子目录。

### 核心模块

| 文件 | 功能 |
|------|------|
| `cli.py` | 命令行入口。解析参数、加载配置、调度抽样/生成/保存流程。 |
| `retrieval.py` | 知识库加载、画师黑名单构建、分类抽样、年龄分级过滤、r18 主题控制、噪音过滤、来源校验。 |
| `assembler.py` | 将抽样 tag 组装为请求载荷，执行冲突检测与消解，并格式化为 LLM 可读的文本。 |
| `client.py` | 加载系统提示词与用户模板，调用 DeepSeek API，解析 JSON 响应，还原 r18 占位符。 |
| `postprocess.py` | 对 API 输出执行画师过滤、禁词替换、冲突消解、来源校验，生成处理日志；含画面美感约束（排版词剔除/风格词≤1/表情词族互斥/现实场所词≤1）。 |
| `config.py` | 项目路径、默认抽样数量、分类映射、黑名单、噪音 meta tag 黑名单（约 380 项）、年龄分级顺序、美感约束词表（LAYOUT_FRAGMENT_TAGS/STYLE_VISUAL_TAGS/EMOTION_GROUP_TAGS/SCENE_PLACE_TAGS）等常量配置。 |
| `tag_classification_rules.py` | tag 年龄分级规则（general / pg12 / r15 / r18 / r18g）。 |

### 维护脚本

| 文件 | 功能 |
|------|------|
| `tools/apply_unclassified_maps.py` | 将 `classify_work/map_*.txt` 人工分类映射回写知识库 v1（分类即排除；支持 `表情动作/擦边`、`物品/擦边`、`人物/擦边` 目标）。 |
| `tools/apply_r18_tier.py` | 应用 r18 两档分类结果：擦边档 rating r18→r15 + 不可见子类 KB 改写；含不上浮保护（触手/血腥等维持硬排除）。 |
| `tools/merge_r18_classify.py` | 汇总校验 6 组分片 r18 分类结果（零遗漏零冲突），输出 `r18_classify_summary.json`。 |
| `tools/build_curated_tags.py` | 从 CSV 自动构建带年龄分级的 `curated_tags.yaml`。可直接运行：`python -m prompt.random_generator.tools.build_curated_tags`。 |
| `tools/build_curated_pools.py` | 从 `curated_tags.yaml` 构建旧版 `curated_pools.json`。 |
| `tools/build_character_pool.py` | 从 Excel 角色表构建 `character_pool.json` 与 `character_pool_series_index.json`。 |
| `tools/sort_character_pool.py` | 按作品/角色排序角色池缓存。 |

### 提示词模板文件

| 文件 | 功能 |
|------|------|
| `system_prompt.md` | 系统提示词，定义模型角色、输出格式（JSON）、风格目标、tag 排序规则、必须避免的 tag 类型。 |
| `system_prompt_v2.md` | version_2 精修（震撼美化版）使用的系统提示词；仅供 `--v2-enhance` 可选路径使用，默认不启用。 |
| `user_prompt.jinja` | Jinja2 用户提示词模板，接收抽样 tag 文本、安全标签、长度约束、主题提示、侧重点权重等变量，生成最终提交给模型的用户消息。 |
| `r18_topics.yaml` | r18 主题分类定义（17 个主题，供 `r18_topic_control` 使用）。 |
| `r18_euphemisms.yaml` | r18 委婉语/替代表达映射。 |
| `semantic_exclude.yaml` | 语义排除规则（无画面语义 / 危险内容 tag 定义）。 |

## 输出格式

每条记录为单行 JSON，包含以下字段：

- `version_1`：生成的提示词（单版本输出；v2 默认关闭）。
- `reasoning`：模型给出的优化说明列表。
- `raw`：DeepSeek API 原始返回。
- `raw_v2`（可选）：仅使用 `--v2-enhance` 时出现，V2 精修版 API 原始返回；实测不建议启用（见 CLI 参数表 `--v2-enhance`）。
- `sampled_tags`：原始抽样 tag，按类别分组。
- `postprocess_log`：后处理流水线日志，包含画师移除、禁词替换、冲突消解、来源校验等。
- `unknown_tags`：无法在数据库或白名单中溯源的 tag 列表。
- `focus_text`（可选）：当配置文件中设置了 `focus_weights` 时，会额外记录生成的侧重点文本。

示例记录：

```json
{
  "version_1": "1girl, solo, long black hair, purple eyes, medium breasts, no clothes, sitting, spread legs, blush, parted lips, looking at viewer, dutch angle, close-up, bedroom, bed sheets, cinematic composition, depth of field",
  "reasoning": [
    "Assembled the faithful tag list from sampled categories."
  ],
  "sampled_tags": {
    "count_gender": ["1girl", "solo"],
    "appearance": ["long black hair", "purple eyes", "medium breasts"],
    "clothing_state": ["no clothes"],
    "pose_action_sex": ["sitting", "spread legs"],
    "expression_reaction": ["blush", "parted lips", "looking at viewer"],
    "camera_shot": ["dutch angle", "close-up"],
    "scene_environment": ["bedroom", "bed sheets"],
    "detail_mood": ["cinematic composition", "depth of field"]
  },
  "postprocess_log": {
    "version_1": {
      "artist_removed": [],
      "filter_applied": true,
      "conflict_log": [],
      "is_valid": true,
      "unknown_tags": []
    }
  },
  "unknown_tags": [],
  "focus_text": "character ~40%, background ~40%, other ~20%"
}
```

## 常见问题与注意事项

### 未知 tag 的处理（`unknown_tags` 与 `is_valid`）

后处理阶段会校验 `version_1` 中的所有 tag 是否可追溯来源。来源包括：

- 原始 CSV 知识库中的 tag；
- 禁词替代标签白名单（如 `white fluid`、`visible bulge` 等）；
- 允许 LLM 补充的互动/环境短 tag 白名单（如 `holding hands`、`wind lifting hair` 等）。

`unknown_tags` 表示未能匹配上述任何来源的 tag。`postprocess_log[version].is_valid` 为 `true` 时表示该版本没有未知 tag。出现未知 tag 通常说明模型生成了知识库外的内容，可通过调整系统提示词或补充白名单解决。

### 为什么需要 `curated_tags.yaml`

`curated_tags.yaml`（位于 `prompt/random_generator/curated_tags.yaml`）是带年龄分级的精选 tag 池，是默认的抽样来源。它的作用：

1. **降噪**：提前过滤掉画师名、角色名、元数据、噪声 tag。
2. **分级**：为每个 tag 标注 `general` / `pg12` / `r15` / `r18` / `r18g`，使 `--max-rating` 可以精确控制生成内容的尺度。
3. **加速**：避免每次生成都扫描整个大 CSV。

首次运行若找不到该文件，模块会自动从 CSV 构建。也可通过 `--rebuild-curated` 或单独运行 `tools/build_curated_tags.py` 手动重建。

### 如何调整生成侧重点（`focus_weights`）

在配置文件中修改 `focus_weights`：

```yaml
focus_weights:
  character: 50
  background: 30
  other: 20
```

上述配置会让生成结果更侧重人物描述（外貌、服装、表情、姿势），相对弱化背景。该权重通过 `focus_text`（如 `character ~50%, background ~30%, other ~20%`）注入到用户提示词中，作为 LLM 的软参考。

### 如何调整年龄分级（`max_rating`）

方法 1：修改配置文件中的 `max_rating`：

```yaml
max_rating: pg12
```

方法 2：命令行覆盖：

```bash
python -m prompt.random_generator.cli generate --max-rating pg12 --count 5
```

`max_rating` 越大，允许抽样的 tag 尺度越宽；越小则越保守。注意 `max_rating` 仅对 `curated_tags.yaml` 生效，旧版 `curated_pools.json` 不带分级信息。

### 使用白名单池控制每类 tag

创建 `my_whitelist.yaml`：

```yaml
category_whitelists:
  enabled: true
  pools:
    character_series:
      - "hatsune miku"
      - "rem (re:zero)"
    appearance:
      - "long hair"
      - "blue eyes"
      - "medium breasts"
    clothing_state:
      - "school uniform"
      - "serafuku"
    scene_environment:
      - "cherry blossoms"
      - "school rooftop"
    detail_mood:
      - "soft lighting"
      - "pastel colors"
```

运行命令：

```bash
python run_generator.py --config my_whitelist.yaml --count 5
```

上述配置会优先从白名单池中抽取对应类别的 tag，未配置的类别（如 `pose_action_sex`、`expression_reaction`、`camera_shot`）仍从知识库 v1 抽样。

## 常见问题与注意事项