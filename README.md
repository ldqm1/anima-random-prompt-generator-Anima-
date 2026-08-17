# anima-random-prompt-generator — Anima 随机提示词生成器

> GitHub 仓库：[anima-random-prompt-generator-Anima-](https://github.com/ldqm1/anima-random-prompt-generator-Anima-)
>
> 简述：基于 DeepSeek API 与 Danbooru 标签知识库的日系二次元少女插画随机提示词生成器。从已分级、已分类的 Danbooru 知识库中按类别随机抽样 tag，调用 DeepSeek 生成并后处理为符合 Anima 模型习惯的结构化提示词。支持年龄分级控制、r18 主题控制、多角色同 IP 角色池、额外要求池化与预算守护批量生成。

基于 DeepSeek API 与 Danbooru 标签知识库，自动生成日系二次元少女插画提示词。

> ⚠️ **AI 生成声明**
>
> 本项目（包括 `prompt/random_generator` 模块的代码、配置文件与本文档）由 **AI 辅助生成**，并非纯人工开发的正式软件项目。请在使用前自行审查代码与配置，理解其行为后再运行；因使用本项目产生的任何结果与风险由使用者自行承担。

> ⚠️ **内容偏向性说明**
>
> 本项目的提示词生成策略（tag 分类与过滤规则、r18 主题控制、角色池、额外要求池、排除清单等）直接反映了**项目作者的个人喜好与审美偏向**。默认面向"可爱少女向"二次元插画，内置规则会主动丢弃男性、纯兽人、深肤/非人肤色、武器、酒精、暴力血腥等 tag。因此生成结果**并非中立或全面的提示词库**，而是按作者偏好裁剪过的输出；若需要无偏或特定方向的生成，请自行调整 `generation_config.yaml`、`config.py` 中的过滤规则与知识库数据。

***

## 快速导航

- [完整自定义指南（推荐阅读）](CUSTOMIZATION.md)：配置体系、知识库、角色池、提示词模板、后处理、批量运行等全部自定义方式。
- [功能简介](#功能简介)
- [环境准备](#环境准备)
- [运行方式](#运行方式)
- [生成配置](#生成配置)
- [数据准备](#数据准备)

## 功能简介

本生成器从项目知识库中按类别随机抽样 tag，作为主题种子调用 DeepSeek API，生成并后处理成符合 Anima 模型习惯的结构化提示词。

生成流程：

1. 从 `知识库/v1` 与 `curated_tags.yaml` 加载已分类、已分级的 tag 数据。
2. 按内部类别（人数性别 / 外貌 / 服装 / 姿势动作 / 表情 / 镜头 / 场景 / 氛围 / 角色）抽样，并做冲突消解、噪音过滤、年龄分级过滤。
3. 将抽样 tag 渲染为结构化用户提示词，调用 DeepSeek API。
4. 对 API 返回结果进行后处理：画师黑名单过滤、禁词替换、冲突消解、自然语言过滤、来源校验、r18 占位符还原。
5. 输出 JSONL，每条记录包含后处理后的 prompt、推理过程与处理日志。

默认面向"可爱少女向"二次元插画，已内置过滤规则，自动丢弃男性、纯兽人、深肤/非人肤色、明确性行为/性器官/暴力血腥等 tag，并在**输入侧**排除无画面语义的介质/噪音 meta tag（共享黑名单约 380 项 + 后缀规则，见 `config.NOISE_META_TAGS`）。

### 知识库人工细粒度分类与两档制

`知识库/v1` 的 tag 已逐条人工细粒度分类（见 `prompt/random_generator/tools/classify_work/` 下的映射文件与报告）：

- **排除项分类即排除**：所有越界内容改写为 `排除/<子类>`（性行为/猎奇血腥/男性雄性/兽化非人/媒体噪音等），
  `config.EXCLUDED_CATEGORIES` 整类丢弃，任何模式（含 r18）均不可见；
- **`排除/性行为` 两档拆分**：拆为"直接暴露档"（显性性器官/精液/体液词，维持硬排除）与
  **"擦边软色情档"**（`表情动作/擦边`、`物品/擦边`、`人物/擦边` 子类，低配额入池，r15 可偶尔出现）；
- **r18 评级两档拆分**：995 条 rating=r18 的 tag 按同一标准细分——263 条擦边软色情降级 r15
  （低配额入池，`表情动作/擦边` 等），732 条直接暴露维持 r18（仅成人模式经 `_supplement_r18_tags` 供给）；
- **子类配额抽样**（`subcategory_quotas`）：每个内部类别按子类配置 min/max 配额，
  **未列入配额表的子类=不设限（unlisted），是趋同放大器，新增子类必须显式列入**。

通过 `--max-rating r18` / `r18g` 可开启成人内容模式，支持：

- **r18 主题控制**：17 类成人主题独立开关/概率/权重/联动，未激活主题的 tag 全链路排除；
- **单人场景限制**：1girl 等单人画面强制不激活需要双人配合的主题（口交/插入/体位）；
- **r18 内容占比**：r18 模式覆盖 focus_weights，提示 LLM 成人内容占 20%、背景压缩至 20%；
- **最小 r18 tag 数**：每样本至少补充若干 r18 评级 tag（可配置）。

### 画面美感约束与大规模趋同收敛

- **输出侧美感约束**（`postprocess._apply_aesthetic_constraints`）：排版/分镜类词剔除
  （comic panel/face chart 等，锚点侧同步禁用 3 个排版锚点）、风格画面词每样本限 1、
  表情词族互斥（同族 1 个 + 全样本 ≤3）、现实场所词每画面限 1；
- **趋同收敛**（`generation_config.yaml`）：构图类子类（构图法则/构图氛围）默认 `max:0`
  （无显式构图，交由模型自由发挥）、灰底滤镜等风格化背景排除、高频姿态池
  （`表情动作/其他动作`）限 `max:1`、背景样式类子类降 max——目标是每天 1200 张量级
  下不产生"既视感"（500 批模拟：构图词 0、高频姿态 0.8%、灰底 0）。
- **随机性保证**：未指定 `--seed` 时每条任务独立随机种子（`random.randint(0, 2**32-1)`），
  实测相邻批 tag 相似度 Jaccard≈0.022，角色池 8940 角色单角色最高 1.3%。

***

## 项目结构

```
anima-rag-knowledge/
├── .env                              # API 密钥（需自行配置）
├── .gitignore
├── LICENSE
├── README.md                         # 本文件
├── run_generator.py                  # 项目根目录快捷入口
│
├── prompt/random_generator/          # 随机提示词生成器核心模块
│   ├── cli.py                        # 命令行入口
│   ├── client.py                     # DeepSeek API 客户端
│   ├── config.py                     # 路径、抽样数量、排除规则、类别映射、噪音黑名单
│   ├── retrieval.py                  # 知识库检索与抽样
│   ├── assembler.py                  # tag 冲突消解
│   ├── postprocess.py                # 后处理与自然语言过滤
│   ├── tag_classification_rules.py   # tag 年龄分级规则
│   ├── system_prompt.md              # LLM system prompt
│   ├── system_prompt_v2.md           # version_2 精修用 system prompt
│   ├── user_prompt.jinja             # LLM user prompt 模板
│   ├── curated_tags.yaml             # 精选 tag 与年龄评级
│   ├── r18_topics.yaml               # r18 主题分类定义
│   ├── r18_euphemisms.yaml           # r18 委婉语/替代表达
│   ├── semantic_exclude.yaml         # 语义排除规则
│   ├── generation_config.yaml        # 生成参数配置（含 r18 主题控制 + subcategory_quotas 子类配额）
│   ├── creative_anchors.yaml         # 创意锚点池（高概念设定；含 enabled 开关）
│   ├── character_pool.json           # 角色池缓存（build_character_pool 生成）
│   ├── character_pool_series_index.json  # IP 级角色池索引
│   ├── requirements.txt              # Python 依赖
│   ├── tests/                        # 单元测试
│   └── tools/                        # 构建/维护脚本
│       ├── apply_unclassified_maps.py    # 人工分类映射回写知识库（分类即排除）
│       └── classify_work/                # 分类审计映射（map_*.txt）
│
├── output/                           # 生成结果输出目录
│   ├── random_prompts.jsonl          # 生成结果（默认输出）
│   └── curated_pools.json            # 精选 tag 池（生成产物）
│
├── source/                           # 原始数据源
│   └── danbooru_e261_updated.csv
│
├── 知识库/                           # 处理后的知识库
│   ├── v1/
│   │   ├── tags_人物.txt
│   │   ├── tags_服饰.txt
│   │   ├── tags_场景.txt
│   │   ├── tags_环境.txt
│   │   ├── tags_画面.txt
│   │   ├── tags_物品.txt
│   │   ├── tags_镜头.txt
│   │   ├── tags_表情动作.txt
│   │   └── tags_二次元角色.txt
│   └── .version
│
└── archive/                          # 归档目录（历史临时文件，可定期清理）
```

***

## 环境准备

### 1. 安装 Python 依赖

在项目根目录执行：

```bash
pip install -r prompt/random_generator/requirements.txt
```

依赖：`openai>=1.0`、`jinja2`、`pyyaml`。

### 2. 配置 DeepSeek API Key

在项目根目录创建 `.env`：

```bash
cp prompt/random_generator/example.env .env
```

编辑 `.env`：

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

> ⚠️ `.env` 已加入 `.gitignore`，请勿提交到公共仓库。

***

## 运行方式

本项目提供根目录快捷入口 `run_generator.py`，所有 `generate` 子命令参数均可直接透传。

### 常用命令

生成 1 条提示词：

```bash
python run_generator.py
```

生成 5 条并保存：

```bash
python run_generator.py --count 5 --output output/prompts.jsonl
```

仅抽样，不调用 API：

```bash
python run_generator.py --dry-run --seed 42
```

仅输出震撼美化版（version_2），并使用 8 个并发 worker：

```bash
python run_generator.py \
  --count 10 \
  --v2-only \
  --workers 8 \
  --output output/v2.jsonl
```

重建 curated 数据后再生成（数据文件更新后使用）：

```bash
python run_generator.py --count 5 --rebuild-curated
```

指定主题与额外要求：

```bash
python run_generator.py \
  --count 3 \
  --subject-control "jk uniform, cherry blossoms" \
  --extra-requirements "画面要体现出可爱的感觉" \
  --output output/cute.jsonl
```

强制/禁止某些 tag：

```bash
python run_generator.py \
  --forced-tags "1girl, solo" \
  --forbidden-tags "male, old" \
  --count 5
```

使用自定义配置文件：

```bash
python run_generator.py --config my_config.yaml --count 5
```

使用 API 平台配置文件（先复制模板再填自己的平台信息）：

```bash
python run_generator.py --api-config prompt/random_generator/api_profiles/example.yaml --count 5
```

`--api-key` / `--api-base` / `--model` 优先级高于 `--api-config` 中的对应字段；API 平台配置文件放在 `prompt/random_generator/api_profiles/` 目录下。

使用白名单角色池（创建 `my_characters.yaml`）：

```bash
python run_generator.py --count 5 --config my_characters.yaml
```

`my_characters.yaml` 示例：

```yaml
character_whitelist:
  enabled: true
  pool:
    - "hatsune miku"
    - "rem (re:zero)"
    - "fubuki (kancolle)"
```

### 完整 CLI 参数表

| 参数                     | 类型    | 默认值                           | 说明                                                 |
| ---------------------- | ----- | ----------------------------- | -------------------------------------------------- |
| `--count`              | `int` | `1`                           | 生成提示词数量                                            |
| `--output`             | `str` | `output/random_prompts.jsonl` | 输出文件路径                                             |
| `--v2-only`            | 标志    | `False`                       | 仅输出震撼美化版（version_2）                               |
| `--seed`               | `int` | `None`                        | 随机种子                                               |
| `--dry-run`            | 标志    | `False`                       | 不调用 API，仅输出抽样与渲染结果                                 |
| `--rebuild-pools`      | 标志    | `False`                       | 重新构建旧版 curated pools 后再生成                         |
| `--rebuild-curated`    | 标志    | `False`                       | 从 CSV 重新构建 curated_tags.yaml 后再生成                |
| `--max-rating`         | `str` | `r15`                         | 最大允许评级：`general` / `pg12` / `r15` / `r18` / `r18g` |
| `--min-tags`           | `int` | `50`                          | 最终 prompt 最少 tag 数                                 |
| `--max-tags`           | `int` | `75`                          | 最终 prompt 最多 tag 数                                 |
| `--subject-control`    | `str` | `""`                          | 主题/主体约束文本；短别名 `-s`                             |
| `--theme-hint`         | `str` | `""`                          | 场景主题提示                                             |
| `--extra-requirements` | `str` | `""`                          | 用户自定义额外要求，如"画面要体现出可爱的感觉"                           |
| `--forced-tags`        | `str` | `""`                          | 强制包含的 tag，逗号分隔                                     |
| `--forbidden-tags`     | `str` | `""`                          | 强制排除的 tag，逗号分隔                                     |
| `--config`             | `str` | `None`                        | 自定义 YAML 配置文件路径                                    |
| `--api-config`         | `str` | `None`                        | API 平台配置文件路径（YAML，可含 `api_key`/`api_base`/`model`），如 `api_profiles/example.yaml` |
| `--api-key`            | `str` | `None`                        | 临时覆盖 API Key                                       |
| `--api-base`           | `str` | `None`                        | 临时覆盖 API Base                                      |
| `--model`              | `str` | `None`                        | 临时覆盖模型名                                            |
| `--character-json`     | `str` | `None`                        | 自定义角色池 JSON 文件路径；格式与 `character_pool.json` 相同，启用后替代默认角色池 |
| `--workers`            | `int` | `4`                           | 并发调用 DeepSeek API 的 worker 数量                      |

> 参数优先级：命令行 > 自定义配置文件 > `generation_config.yaml` > `config.py` 默认值。

***

## 生成配置

默认配置文件：

```text
prompt/random_generator/generation_config.yaml
```

完整默认配置：

```yaml
# 允许抽样的最大年龄分级（general / pg12 / r15 / r18 / r18g）
max_rating: r15

# r18 模式下每个样本至少抽到的 r18 评级 tag 数量（0 表示不强制；仅 max_rating=r18 时生效）。
# 补充抽样仍会通过全部清洗规则，不会绕过男性/扶她/福瑞/r18g 等禁用类别过滤。
min_r18_tags_per_sample: 15

# r18 模式下注入到 LLM 用户提示词的自定义指令文本（可多行，原样注入）。
# 默认留空表示不注入；该字段仅提供注入机制，不会解除系统提示词中的分级与清洗规则。
r18_instructions: ""

# 每个内部类别的抽样数量
# 总计应 >= 50，并留出余量，以便 LLM 在丢弃不适合的 tag 后仍能满足最终 prompt 50+ tag 的长度要求。
sample_counts:
  count_gender: 2         # 人数与性别
  appearance: 20         # 外貌
  clothing_state: 20      # 服装与穿着状态
  pose_action_sex: 20    # 姿势/动作/体位
  expression_reaction: 20 # 表情与反应
  camera_shot: 5         # 镜头/景别/构图
  scene_environment: 20  # 场景与环境
  detail_mood: 9         # 画面质感/氛围

# r18 模式专用抽样数量：仅 max_rating 为 r18/r18g 时覆盖上方的 sample_counts。
r18_sample_counts:
  count_gender: 2
  appearance: 16
  clothing_state: 15
  pose_action_sex: 16
  expression_reaction: 15
  camera_shot: 5
  scene_environment: 14
  detail_mood: 6

# r18 标签主题控制（仅 max_rating=r18/r18g 时生效）
# 根据 r18_topics.yaml 的 17 个主题，逐类调节出现概率。每个主题支持：
#   enabled:          该主题是否参与（false = 主题下全部 tag 不出现）
#   mode:             fixed（固定出现） / probabilistic（按概率出现） / weighted（按权重调节）
#   count:            该主题的目标 tag 数量（主题类可设 count>1 使主题集中出现）
#   probability:      probabilistic 模式的出现概率（0-1）
#   weight:           加权模式下的抽样权重
#   linked_topics:    联动主题列表；本主题激活时以 link_probability 概率同时激活列表中的主题
#   link_probability: 联动触发概率（默认 0.8）
r18_topic_control:
  enabled: true
  topics:
    nudity_exposure:        # 裸露与暴露：非主题类，固定出现 1
      mode: fixed
      count: 1
    reactions:              # 表情与身体反应：固定小数量出现
      mode: fixed
      count: 2
    body_features:          # 身体部位与外观特征：高频参与
      mode: weighted
      weight: 2
      count: 2
    bondage:                # 束缚/支配/调教：概率出现，出现时抽 3 个集中构成主题
      mode: probabilistic
      probability: 0.3
      count: 3
      linked_topics: [clothing_props]
      link_probability: 0.8
    oral:                   # 口交与舌：概率出现
      mode: probabilistic
      probability: 0.3
      count: 2
      linked_topics: [cum]
      link_probability: 0.5
    # ...（其余主题类似，完整列表见 generation_config.yaml 与 r18_topics.yaml）

  # 单人场景（1girl/1boy 等非多人标记）下的主题限制。
  # 单人画面无法自然呈现需要两人配合的主题，启用后这些主题在单人场景强制不激活；
  # 多人场景（2girls 等）不受影响。
  solo:
    enabled: true
    disabled_topics: [oral, penetration, positions]

# 最终提示词长度约束（tag 数量）
min_tags: 40
max_tags: 60

# 生成侧重点权重（百分比）
# 用于提示 LLM 在最终 prompt 中各类描述的占比
focus_weights:
  character: 40      # 角色相关：人数/性别、外貌、服装、表情、姿势/动作
  background: 40     # 背景相关：场景、环境、物件、光影、镜头/氛围
  other: 20          # 其他/缓冲

# r18 模式专用生成侧重点权重（百分比）
# 仅 max_rating 为 r18/r18g 时覆盖上方的 focus_weights；不改变任何类别的抽样数量。
r18_focus_weights:
  character: 40      # 角色相关
  background: 20     # 背景相关（r18 模式下压缩）
  r18: 20            # r18 内容（成人主题 tag 占 20%）
  other: 20          # 其他/缓冲

# 多角色场景（如 2girls）触发时的自动调整
# - tag 数量限制：min_tags 与 max_tags 各增加 tag_count_bonus（n）
# - 生成侧重点：character 占比 + focus_character_bonus（m），从 background 与 other 中按比例扣减
multi_character:
  tag_count_bonus: 30       # n，默认 20
  focus_character_bonus: 5  # m，默认 10（百分比）

# DeepSeek API 调用参数
deepseek:
  temperature: 0.7
  max_tokens: 1000
  reasoning_effort: "none"  # "none" 关闭推理（更快/不占 max_tokens/更便宜），或 "low"/"medium"/"high"
  timeout: 120              # 单次 API 调用超时秒数
  max_parse_retries: 2      # 解析失败（空内容/JSON 异常）时的最大重试次数

# 默认输出目录
output_dir: output

# 用户自定义额外要求（字符串；extra_requirements_pool.enabled 为 true 时优先使用池化配置）
extra_requirements: |
  画面要体现出可爱的感觉。

# 额外要求池化配置（互斥组按 weight 抽一项，可选项按 probability 独立抽取）
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

# Excel 角色池配置
character_pool:
  enabled: true
  file: null              # null 表示使用默认路径 prompt/random_generator/character_pool.json
  prefer_same_ip_for_multiple: true  # 多角色场景下优先从同一作品抽样
  use_core_appearance: true           # 是否向 LLM 注入角色核心外貌词
  use_core_clothing_probability: 0.8  # 使用核心服饰词作为基础服饰的概率
  series_index_file: null             # IP 索引路径；null 时自动使用 <file_stem>_series_index.json

# 白名单角色池（旧版）
character_whitelist:
  enabled: false
  pool: []

# 通用类别白名单池
category_whitelists:
  enabled: false
  pools:
    人数与性别: []
    外貌: []
    服装与穿着状态: []
    姿势/动作/体位: []
    表情与反应: []
    镜头/景别/构图: []
    场景与环境: []
    画面质感/氛围: []
    二次元角色: []
```

### 子类配额抽样（subcategory_quotas）

每个内部类别下的子类配额，控制各子类每批抽样数量（人工细分类后替代均匀抽样）：

```yaml
subcategory_quotas:
  pose_action_sex:            # 姿势/动作/体位
    静止姿态: {min: 1, max: 4}   # min: 每批至少抽到的数量（保证冷门子类出现）
    动态动作: {min: 1, max: 5}
    其他动作: {min: 0, max: 1}   # 高频姿态池限流（趋同收敛）
    擦边: {min: 0, max: 1}      # 擦边软色情档：偶尔出现
    性爱动作: {min: 0, max: 0}   # r15 默认完全排除；r18 模式由补充抽样供给
  camera_shot:
    构图法则: {min: 0, max: 0}   # 默认无显式构图，交由模型自由发挥（趋同收敛）
```

规则：

- `min` 先满足，再在 `max` 约束下随机补足到 `sample_counts` 的数量；
- **未列入配额表的子类 = 不设限（unlisted）**——补足阶段会高概率抽取，是"高频趋同"的放大器，
  新增子类必须显式列入配额表并设置 max；
- 擦边软色情档（`表情动作/擦边`/`物品/擦边`/`人物/擦边`）与直接暴露档
  （`排除/性行为` 与维持 r18 的 tag）由分类体系（`config.CATEGORY_MAPPINGS` +
  `curated_tags.yaml` 评级）驱动，配额仅控制出现频率。

### 配置项说明

| 配置项                     | 说明                 | 调整建议                                             |
| ----------------------- | ------------------ | ------------------------------------------------ |
| `max_rating`            | 允许抽样的最大年龄分级        | 更保守设为 `pg12`，更开放设为 `r18`                         |
| `min_r18_tags_per_sample` | r18 模式每样本最少 r18 tag 数 | 默认 `15`；为 `0` 时不强制补充                           |
| `r18_instructions`      | r18 模式注入 LLM 的自定义指令 | 可多行原样注入；仅提供注入机制，不解除系统分级与清洗规则             |
| `sample_counts`         | 每个内部类别抽样数量         | 总计建议 ≥ 50，以便 LLM 丢弃不适合 tag 后仍满足 `min_tags`       |
| `r18_sample_counts`     | r18 模式专用抽样数量        | 仅 r18/r18g 模式覆盖 `sample_counts`，非 r18 模式不受影响       |
| `r18_topic_control`     | r18 主题控制             | 17 类主题独立开关/模式/数量/权重/联动；`solo` 限制单人场景主题     |
| `subcategory_quotas`    | 子类配额抽样（min/max）     | 控制各子类出现频率；**未列入的子类=不设限（趋同放大器），新增子类必须列入** |
| `min_tags` / `max_tags` | 最终 prompt tag 数量区间 | 需要更简短时同时调低                                       |
| `focus_weights`         | 角色/背景/细节占比         | 提高 `character` 让人物更突出，提高 `background` 让场景更突出     |
| `r18_focus_weights`     | r18 模式专用占比          | 仅 r18/r18g 模式覆盖；r18 占 20%、背景压缩至 20%，不改变抽样数量   |
| `multi_character`       | 多角色场景自动调整          | 命中 2girls 等标记时放宽 tag 数量上限并提升角色占比             |
| `deepseek`              | DeepSeek API 调用参数  | `reasoning_effort: "none"` 关闭推理更快更省；`max_tokens` 控制返回长度 |
| `output_dir`            | 默认输出目录             | 命令行未指定 `--output` 时，输出文件存放位置                     |
| `extra_requirements`    | 自定义风格/氛围要求（字符串）   | 例如"画面要体现出可爱的感觉""避免冷峻表情"；池化启用时作为兼容保留     |
| `extra_requirements_pool` | 额外要求池化配置         | 支持互斥组（按 weight 选一项）与可选项（按 probability 独立抽取）   |
| `character_pool`        | Excel / 自定义 JSON 角色池配置 | 启用后优先从角色池抽样，支持同 IP 多角色、核心外貌注入与 IP 权重     |
| `character_whitelist`   | 白名单角色池（旧版）         | 指定固定角色列表；新版请使用 `category_whitelists.pools.二次元角色` |
| `category_whitelists`   | 通用类别白名单池           | 对每个内部类别分别指定白名单，未指定的类别仍从知识库 v1 抽样                 |

### 使用白名单池控制每类 tag

创建 `my_whitelist.yaml`：

```yaml
# pools 的键名可使用中文展示名
category_whitelists:
  enabled: true
  pools:
    二次元角色:
      - "hatsune miku"
      - "rem (re:zero)"
    外貌:
      - "long hair"
      - "blue eyes"
      - "medium breasts"
    服装与穿着状态:
      - "school uniform"
      - "serafuku"
    场景与环境:
      - "cherry blossoms"
      - "school rooftop"
    画面质感/氛围:
      - "soft lighting"
      - "pastel colors"
```

运行：

```bash
python run_generator.py --config my_whitelist.yaml --count 5
```

说明：

- 只有 `enabled: true` 时白名单才生效。
- 每个类别的 pool 独立配置，pool 为空或未指定的类别会回退到知识库 v1 抽样。
- 键名同时支持中文展示名与内部英文键名（如 `appearance` 与 `外貌` 等价）。

### 使用 Excel 角色池

项目中的 `source/D站200图以上角色及作品名单 翻译 角色外貌描写词.xlsx` 包含大量二次元角色及其作品、触发词与核心外貌描写词。启用 `character_pool` 后，生成器会优先从该角色池中抽样，并在多角色场景下尽量让角色来自同一作品/IP，同时把角色的核心外貌词注入 prompt。

使用步骤：

1. 先构建角色池缓存：

```bash
python -m prompt.random_generator.tools.build_character_pool
```

该命令会生成：

- `prompt/random_generator/character_pool.json`：结构化角色缓存。
- `prompt/random_generator/character_pool_series_index.json`：IP 级索引，包含每个作品的开关、男性角色过滤和权重。

2. 创建配置文件 `my_char_pool.yaml` 并启用角色池：

```yaml
character_pool:
  enabled: true
  prefer_same_ip_for_multiple: true
  use_core_appearance: true
  use_core_clothing_probability: 0.5
```

3. 运行生成：

```bash
python run_generator.py --config my_char_pool.yaml --count 5
```

说明：

- 启用 `prefer_same_ip_for_multiple` 后，当 `count_gender` 抽到 `2girls` 等多人 tag 时，生成器会优先从同一 `series_tag` 中抽取多个不同角色；若该作品角色不足，则自动从其他作品补充。
- `use_core_appearance` 为 `true` 时，每个角色的 `core_appearance_tags` 会被写入 user prompt，并明确告知 LLM 必须保留。
- `use_core_clothing_probability` 控制是否使用角色的 `core_clothing_tags` 作为基础服饰：命中概率时以核心服饰为主并允许不冲突的 sampled clothing 叠加；未命中时完全使用 sampled clothing。
- 可与 `category_whitelists.pools.二次元角色` 联用，此时仅从这些白名单角色中筛选（要求角色在 Excel 角色池中存在）。

#### IP 权重与索引排序

`character_pool_series_index.json` 中每个 IP 都有 `weight` 字段（默认 `10`）。权重越高，该作品被抽中的概率越大。重新运行 `build_character_pool` 时会保留已有的 `weight`、 `enabled` 和 `allow_male` 设置，并将 `enabled: true` 的项排在前面，方便手动修改权重。

示例：将 `kantai_collection` 的权重设为 `50`，其他保持 `10`，则舰队 Collection 被选中的概率会显著高于其他作品。

```json
{
  "series_tag": "kantai_collection",
  "series_name_cn": "舰队Collection",
  "enabled": true,
  "allow_male": true,
  "weight": 50,
  "character_count": 422
}
```

### 使用自定义 JSON 角色池

如果不想使用 Excel 构建的全量角色池，或想临时指定单个/少量角色，可通过 `--character-json` 传入自定义 JSON 文件。文件格式与 `character_pool.json` 完全一致：

```json
[
  {
    "character_tag": "hatsune_miku",
    "series_tag": "vocaloid",
    "series_name_cn": "VOCALOID",
    "trigger_tags": ["hatsune miku", "vocaloid"],
    "core_appearance_tags": ["1girl", "aqua eyes", "very long hair", "aqua hair", "twintails"],
    "core_clothing_tags": ["detached sleeves"],
    "is_male": false
  }
]
```

使用命令：

```bash
python run_generator.py --character-json my_characters.json --count 5 --dry-run
```

说明：

- 提供 `--character-json` 后，角色池会被强制启用并替换为指定文件，无需修改 `generation_config.yaml`。
- 若同目录下存在 `<文件名>_series_index.json`（如 `my_characters_series_index.json`），则自动作为 IP 索引，支持 `enabled` / `allow_male` / `weight` 控制。
- 文件中只有 `1` 个角色时，每次生成都会固定抽到该角色，可作为“指定角色”模式使用。
- 文件中只有少量角色时，生成器会从中随机抽取，相当于自定义小角色池。

### 使用 extra_requirements 池化

当需要让 LLM 在不同风格/氛围要求中随机切换时，可使用 `extra_requirements_pool`。启用后，每次生成会从互斥组中按权重选一项，并按概率独立抽取若干可选项，最终拼接为额外要求注入 prompt。

配置示例：

```yaml
extra_requirements_pool:
  enabled: true
  mutex_groups:
    - items:
        - text: "画面要体现出可爱的感觉。"
          weight: 10
        - text: "画面要体现出唯美的感觉。"
          weight: 5
    - items:
        - text: "背景是夜晚的城市。"
          weight: 7
  optional_items:
    - text: "加入一些飘落的花瓣。"
      probability: 0.3
    - text: "角色露出微笑。"
      probability: 0.5
```

说明：

- `mutex_groups` 可配置多个互斥列表，每个列表内部按 `weight` 抽取 **恰好一项**。
- `optional_items` 中的每项按 `probability` 独立判断是否加入，可以同时选中多项。
- 若 `enabled: false`，则回退到旧版 `extra_requirements` 字符串。
- 命令行 `--extra-requirements` 会覆盖池化配置（优先级最高）。

***

## 输出格式

每条结果为单行 JSON，结构如下：

```json
{
  "version_1": "1girl, solo, long black hair, purple eyes, ...",
  "version_2": "1girl, solo, long black hair, purple eyes, ...",
  "reasoning": ["选择 tag 的理由..."],
  "raw": { "id": "...", "choices": [...] },
  "postprocess_log": {
    "version_1": { "is_valid": true, "unknown_tags": [], ... },
    "version_2": { ... }
  },
  "unknown_tags": [],
  "sampled_tags": { ... },
  "focus_text": "character ~40%, background ~40%, other ~20%"
}
```

字段说明：

| 字段                        | 说明                |
| ------------------------- | ----------------- |
| `version_1` / `version_2` | 后处理后的两条提示词（内容一致）  |
| `reasoning`               | LLM 选择 tag 的思考过程  |
| `raw`                     | DeepSeek API 原始返回 |
| `postprocess_log`         | 后处理日志             |
| `unknown_tags`            | 无法追溯到数据库或白名单的 tag |
| `sampled_tags`            | 从知识库中抽取的原始 tag    |
| `focus_text`              | 角色/背景/细节比例提示      |

***

## 数据准备

若需从原始数据重新构建知识库，请从上游 [BuXinZi/anima-rag-knowledge](https://github.com/BuXinZi/anima-rag-knowledge) 获取 `scripts/` 处理脚本。

构建精选 tag 池：

```bash
python -m prompt.random_generator.tools.build_curated_tags
python -m prompt.random_generator.tools.build_curated_pools
```

***

## 数据来源

### 上游项目

本项目基于 **BuXinZi（炼天魔尊分魂-不信子）** 维护的 [anima-rag-knowledge](https://github.com/BuXinZi/anima-rag-knowledge) 仓库修改而来。

原仓库核心用途：

- 为 [ComfyUI Easy-RAG](https://github.com/nregret/Comfyui-Easy-RAG) 提供 Anima 模型专用的提示词知识库；
- 整理并分类 Danbooru 标签、角色、画师等数据；
- 提供插画、漫画、视频、局部重绘等多场景模板。

当前仓库在保留原知识库数据的基础上，新增了 `prompt/random_generator` 模块，用于基于 DeepSeek API 自动生成随机二次元少女提示词。

### 原始数据

| 原始数据              | 来源                                                                                                                                                                   | 用途         |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| Danbooru e261 标签集 | QQ群友天痕（翻译+分类）                                                                                                                                                        | 标签主库       |
| Anima 标签白名单       | [BetaDoggo/danbooru-tag-list](https://github.com/BetaDoggo/danbooru-tag-list/releases) (`anima-1.0.csv`)                                                             | 标签过滤参考     |
| 角色/画师索引           | [fulletLab/comfyui-anima-style-nodes](https://github.com/fulletLab/comfyui-anima-style-nodes) → [Laxhar/noob-wiki](https://huggingface.co/datasets/Laxhar/noob-wiki) | 角色库、画师库    |
| 画师精选、提示词示例        | [nregret/Comfyui-Easy-RAG](https://github.com/nregret/Comfyui-Easy-RAG) (`rag/`)                                                                                     | 精选画师、提示词参考 |
| 角色验证数据            | [hbl917070/DrawingSpells](https://github.com/hbl917070/DrawingSpells) → [NebulaeWis/e621-2024](https://huggingface.co/datasets/NebulaeWis/e621-2024-webp-4Mpixel)    | 角色中文名匹配    |

***

## 注意事项

1. **上游来源**：本项目是基于 BuXinZi 的 [anima-rag-knowledge](https://github.com/BuXinZi/anima-rag-knowledge) 仓库修改/衍生而来，遵循原仓库的 MIT License 与公开数据声明。
2. **API 费用**：每次生成调用 DeepSeek API，建议将 `deepseek.reasoning_effort` 设为 `"none"` 以关闭推理 token 消耗；请按需控制生成数量。
3. **内容合规**：默认配置已过滤大量越界内容（男性、纯兽人、非人肤色、武器、酒精、暴力血腥等），并在**输入侧**排除无画面语义的介质/噪音 meta tag（`config.NOISE_META_TAGS`，约 380 项）。r18/r18g 模式会启用主题控制与单人场景限制，但 LLM 仍可能输出越界描述，请按实际合规要求使用。
4. **自然语言短语**：后处理已过滤清单体和过长短语，但仍建议人工抽查最终 prompt。
5. **.env 安全**：`.env` 文件包含 API 密钥，已加入 `.gitignore`，请勿提交到公共仓库或保存明文密钥副本。**临时 `--api-key` 传入的密钥也只会存在于当前进程，不会写入任何文件。**
6. **归档目录**：`archive/` 目录存放历史临时文件，不影响项目运行，可定期清理。
7. **配额表纪律**：`subcategory_quotas` 未列入的子类=不设限（unlisted），补足阶段会被高概率抽取，是"高频趋同"的放大器——新增子类（含擦边档）必须显式列入配额表。
8. **美感约束**：输出侧 `postprocess._apply_aesthetic_constraints` 会剔除排版/分镜类词、限制风格词（≤1）、表情词族互斥（≤3）、现实场所词（≤1）；若需完全自定义画面语言，请同步调整 `config.LAYOUT_FRAGMENT_TAGS` / `STYLE_VISUAL_TAGS` / `EMOTION_GROUP_TAGS` / `SCENE_PLACE_TAGS` 与锚点池 `creative_anchors.yaml`。

***

## 作者与致谢

### 原作者

**炼天魔尊分魂-不信子 (BuXinZi)**

- 仓库：[anima-rag-knowledge](https://github.com/BuXinZi/anima-rag-knowledge)
- 平台：GitHub · Civitai
- 说明：未开设任何 QQ 群/微信群/付费频道。

BuXinZi 是原 anima-rag-knowledge 知识库的作者，负责整理 Danbooru 标签分类、角色库、画师库、多场景模板以及 Easy-RAG 适配工作。

### 当前维护者

**ldqm1**

- GitHub：[anima-random-prompt-generator-Anima-](https://github.com/ldqm1/anima-random-prompt-generator-Anima-)

当前仓库在原 anima-rag-knowledge 的基础上进行了修改与扩展，主要新增了 `prompt/random_generator` 随机提示词生成模块。修改后的代码仍遵循原仓库 MIT License，知识库数据继续遵循原作者的公开数据声明。

### 致谢

感谢 BuXinZi 公开整理并维护 Anima 知识库，以及下列社区项目提供的公开数据：

- [BetaDoggo/danbooru-tag-list](https://github.com/BetaDoggo/danbooru-tag-list)
- [fulletLab/comfyui-anima-style-nodes](https://github.com/fulletLab/comfyui-anima-style-nodes) / [Laxhar/noob-wiki](https://huggingface.co/datasets/Laxhar/noob-wiki)
- [nregret/Comfyui-Easy-RAG](https://github.com/nregret/Comfyui-Easy-RAG)
- [hbl917070/DrawingSpells](https://github.com/hbl917070/DrawingSpells)

***

## 许可

- 处理脚本（`prompt/random_generator/`）：**MIT License**
- 知识库文件（`知识库/`）：整理自公开数据源，**永久免费开放**

> ⚠️ 如果你在付费渠道获得此知识库，你被骗了。本仓库始终免费提供最新版本。

