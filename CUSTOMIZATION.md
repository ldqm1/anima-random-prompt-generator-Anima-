# Anima 随机提示词生成器 — 项目自定义指南

本文档完整介绍本项目的自定义方式，从「只改 YAML」到「改 Python 代码」逐层深入。阅读顺序建议：

1. [配置优先级](#1-配置优先级) — 先理解参数从哪来
2. [generation_config.yaml 全字段](#2-generation_configyaml-全字段) — 日常 90% 的自定义都在这
3. [知识库自定义](#3-知识库自定义) — 数据源怎么改
4. [角色池自定义](#4-角色池自定义) — 角色/IP 抽样怎么改
5. [提示词模板自定义](#5-提示词模板自定义) — LLM 行为怎么改
6. [代码级自定义（config.py / 后处理）](#6-代码级自定义configpy--后处理)
7. [常见自定义场景速查](#7-常见自定义场景速查)

---

## 1. 配置优先级

参数合并顺序（优先级从高到低）：

```
命令行 --xxx > 用户自定义配置文件 --config my.yaml > generation_config.yaml > config.py 默认值
```

- 命令行参数见 [README 完整 CLI 参数表](README.md#完整-cli-参数表)。
- `--config my.yaml` 只需写你要覆盖的键，未写到的项沿用 generation_config.yaml 与 config.py。
- `--api-key / --api-base / --model` 仅临时覆盖，不会写回任何文件。
- 配置深度合并规则：字典逐层合并；`extra_requirements` 等整值字段整体替换。

---

## 2. generation_config.yaml 全字段

默认文件：`prompt/random_generator/generation_config.yaml`。

### 2.1 内容分级

```yaml
# 允许抽样的最大年龄分级（general / pg12 / r15 / r18 / r18g）
max_rating: r15

# r18 模式下每样本最少抽到的 r18 评级 tag 数（0 = 不强制）
min_r18_tags_per_sample: 15
```

| 字段 | 说明 | 建议 |
|---|---|---|
| `max_rating` | 抽样与提示词的内容上限 | 更保守 `pg12`，更开放 `r18` |
| `min_r18_tags_per_sample` | 仅 `max_rating=r18/r18g` 生效 | 调高则露骨 tag 更密集；为 0 关闭强制补充 |

### 2.2 抽样数量

```yaml
sample_counts:        # 非 r18 模式各内部类别抽样数量
  count_gender: 2
  appearance: 20
  clothing_state: 20
  pose_action_sex: 20
  expression_reaction: 20
  camera_shot: 5
  scene_environment: 20
  detail_mood: 9

r18_sample_counts:    # 仅 r18/r18g 模式覆盖上方
  count_gender: 2
  appearance: 16
  # ...
```

- 内部类别共 8 类，`character_series`（角色）由角色池决定数量。
- 总量建议 ≥ 50，给 LLM 留丢弃余量以达成 `min_tags`。
- 注意：`sample_counts` 与 `knowledge_sample_counts` 视为同一含义，后者优先级更高（`cli._build_config` 中先 `sample_counts` 后 `knowledge_sample_counts`）。

### 2.3 r18 主题控制

```yaml
r18_topic_control:
  enabled: true
  topics:
    nudity_exposure:          # 主题名（见 r18_topics.yaml 的 17 个主题）
      mode: fixed             # fixed / probabilistic / weighted
      count: 1                # 目标 tag 数量
      probability: 0.3        # probabilistic 模式出现概率
      weight: 2               # weighted 模式抽样权重
      linked_topics: [cum]    # 激活时联动激活的主题
      link_probability: 0.5   # 联动触发概率
  solo:
    enabled: true
    disabled_topics: [oral, penetration, positions]  # 单人场景强制不激活
```

| 模式 | 行为 |
|---|---|
| `fixed` | 固定出现（非主题类推荐，如裸露/表情小数量） |
| `probabilistic` | 按 `probability` 出现，命中后抽 `count` 个 |
| `weighted` | 始终可参与，仅按 `weight` 调节权重（默认） |

要点：
- `enabled: false` 的主题，其下全部 tag 在主抽样与 r18 补充中都不出现。
- `count > 1` 使主题集中出现（如 bondage 抽 3 个构成主题）。
- `solo.disabled_topics` 仅在单人场景（1girl/1boy 等非多人标记）强制不激活；多人场景不受影响。判定在 `count_gender` 与 `character_series` 预抽样之后执行（`character_series` 可能把 2girls 降级为 1girl）。
- 主题清单与全部可抽 tag 见 `r18_topics.yaml`；每个 r18 tag 的含蓄短句见 `r18_euphemisms.yaml`（用于占位符还原）。

### 2.4 提示词长度与侧重点

```yaml
min_tags: 40
max_tags: 60

focus_weights:            # 提示 LLM 各类描述占比
  character: 40
  background: 40
  other: 20

r18_focus_weights:        # 仅 r18/r18g 覆盖上方
  character: 40
  background: 20
  r18: 20
  other: 20
```

- `focus_weights` 只影响提示 LLM 的占比文本，不改变任何类别抽样数量。
- r18 模式下背景压缩到 20%、r18 内容占 20%（用户明确不要扣背景 tag 配额，故仅提示占比）。

### 2.5 多角色场景

```yaml
multi_character:
  enabled: true          # 总开关；false 时人数/性别强制 1girl
  probability: 0.25      # 多人角色占比（0-1）：每条样本掷骰，命中则 2girls 否则 1girl
  tag_count_bonus: 30    # 命中多角色时 min_tags/max_tags 各 +n
  focus_character_bonus: 5  # character 占比 +m%，从 background/other 按比例扣减
```

- `enabled: false`：`count_gender` 强制为 `1girl`，`cli` 的多人判定也失效。
- `probability`：在 `random.seed` 之后掷骰，命中则 `_allowed_count_gender={"2girls"}`，未命中 `={"1girl"}`。
- 语义要求「基础始终抽单人 + 最终按 probability 多人」。

### 2.6 DeepSeek API 参数

```yaml
deepseek:
  temperature: 0.7
  max_tokens: 1000
  reasoning_effort: "none"   # "none" 关闭推理（更快/更省），或 low/medium/high
  timeout: 120
  max_parse_retries: 2
```

- `reasoning_effort: "none"` 必须带引号，否则 YAML 解析为 `null`（等于不发送该参数）。
- 开启推理会占用 `max_tokens`，需相应调大。

### 2.7 输出与额外要求

```yaml
output_dir: output

extra_requirements: |
  画面要体现出可爱的感觉。

extra_requirements_pool:
  enabled: true
  mutex_groups:
    - skip_probability: 0.3
      items:
        - text: "画面要体现出可爱的感觉。"
          weight: 5
        - text: "画面要体现出唯美的感觉。"
          weight: 10
          excludes:            # 条目级互斥：与已抽中条目冲突则排除
            - "背景是洒满金色阳光的黄昏。"
  optional_items:
    - text: "加入随风飘落的樱花花瓣。"
      probability: 0.12
```

- `extra_requirements_pool.enabled: true` 时优先使用池化配置，旧字符串作为兼容保留。
- `mutex_groups`：每组按 weight 加权抽 1 项；`skip_probability` 整组跳过。
- `optional_items`：每项按自身 `probability` 独立决定。
- 命令行 `--extra-requirements` 优先级最高，会覆盖池化配置。

### 2.8 角色池 / 白名单

```yaml
character_pool:
  enabled: true
  file: null                                  # null = 默认 character_pool.json
  prefer_same_ip_for_multiple: true           # 多角色优先同 IP
  use_core_appearance: true                   # 注入角色核心外貌词
  use_core_clothing_probability: 0.8          # 用核心服饰作基础服饰的概率
  series_index_file: null                     # null = 自动定位 <file_stem>_series_index.json

character_whitelist:      # 旧版白名单角色池
  enabled: false
  pool: []

category_whitelists:      # 通用类别白名单池
  enabled: false
  pools:
    人数与性别: []
    外貌: []
    # ...
```

详见第 4 节。

---

## 3. 知识库自定义

### 3.1 目录结构

```
知识库/
├── .version
└── v1/
    ├── tags_人物.txt           # 人物（外貌/表情/姿势 等，按 CAT 细分）
    ├── tags_服饰.txt           # 服饰
    ├── tags_表情动作.txt        # 表情/动作/姿势/体位
    ├── tags_镜头.txt           # 镜头/构图
    ├── tags_场景.txt           # 场景
    ├── tags_环境.txt           # 环境/天气/氛围
    ├── tags_画面.txt           # 画面质量/风格/光照
    ├── tags_物品.txt           # 物品
    └── tags_二次元角色.txt       # 角色/作品名
```

- 知识库 v1 行格式：`[DOMAIN:标签] [CAT:分类/子分类] 英文tag | 中文翻译`。
- 文件 → 内部类别映射在 `config.KNOWLEDGE_TAG_FILES`；CSV 分类 → 内部类别映射在 `config.CATEGORY_MAPPINGS`。
- 直接增删文本行即可自定义；修改后无需重建缓存（每次启动重新加载过滤）。

### 3.2 curated_tags.yaml（已入池 tag 与评级）

`prompt/random_generator/curated_tags.yaml` 是**默认采样源**，格式：

```yaml
appearance:
- tag: long hair
  rating: general
  chinese: 长发
```

- `rating` 取值 `general / pg12 / r15 / r18 / r18g`，按 `max_rating` 过滤。
- 入池 tag 按语义人工/审核判定，不受 `semantic_exclude.yaml` 影响。
- 重建命令：`python -m prompt.random_generator.tools.build_curated_tags`（从 `source/danbooru_e261_updated.csv` 构建，top_n=500）。
- 手动编辑：直接改 yaml 即可，改后无需重建（程序优先读已有文件）。

### 3.3 semantic_exclude.yaml（未入池 tag 排除）

作用于**未入池**的知识库残留 tag：

```yaml
always:        # 所有模式一律排除
  - tag: "censor bar"
r18g_tier:     # 仅低于 r18g 的分级排除，r18g 模式放行
  - tag: "corpse"
```

### 3.4 评分/分级规则

- `prompt/random_generator/tag_classification_rules.py`：补充的年龄分级规则（`EXTRA_EXACT_OVERRIDES` 精确覆盖、`EXTRA_RATING_KEYWORDS` 关键词、`R18_MANUAL_WHITELIST`）。
- 规则遵循「客观字面表意」，不考虑引申意/隐喻/梗文化含义。

---

## 4. 角色池自定义

### 4.1 角色池文件

- `prompt/random_generator/character_pool.json`：结构化角色缓存，条目格式：

```json
{
  "character_tag": "hatsune_miku",
  "series_tag": "vocaloid",
  "series_name_cn": "VOCALOID",
  "trigger_tags": ["hatsune miku", "vocaloid"],
  "core_appearance_tags": ["1girl", "aqua eyes", "very long hair", "aqua hair", "twintails"],
  "core_clothing_tags": ["detached sleeves"],
  "is_male": false
}
```

- 角色池 IP 抽样概率 = `log(character_count) × weight`。
- 仅 `enabled: true` 的 IP 参与抽样（`character_pool_series_index.json`）。

### 4.2 IP 级索引（手动开关与权重）

`prompt/random_generator/character_pool_series_index.json`：

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

- `enabled: false`：该 IP 不参与抽样。
- `allow_male: false`：该 IP 不提供男性角色（纯女性场景默认排除男性，见下）。
- `weight`：权重越高越易被抽中（默认 10）。
- 重新运行 `build_character_pool` 时会**保留**手动修改的 `weight / enabled / allow_male` 字段，只重算 `character_count`。

### 4.3 男性角色过滤

- 纯女性场景（`1girl/2girls` 等）默认排除男性角色；仅当 `count_gender` 含男性标记（`1boy/2boys/hetero` 等）才允许，且仍受 IP 的 `allow_male` 过滤。
- 判定函数：`retrieval._scene_allows_male_character`。

### 4.4 构建/维护工具

| 工具 | 命令 | 作用 |
|---|---|---|
| 构建角色池 | `python -m prompt.random_generator.tools.build_character_pool` | 从 Excel 角色表构建 `character_pool.json` + 系列索引 |
| IP 去重排序 | `python -m prompt.random_generator.tools.sort_character_pool` | 合并重复 IP、重算角色数、排序 |
| 自定义 JSON | `python run_generator.py --character-json my.json` | 直接指定角色池文件（强制启用，替代默认池） |

### 4.5 白名单池

- `character_whitelist`（旧版）：固定角色列表。
- `category_whitelists.pools`（通用）：对每个内部类别分别指定白名单；`enabled: true` 才生效；池为空的类别回退知识库 v1。
- 键名支持中文展示名与内部英文键名（`appearance` ≡ `外貌`），映射在 `config.CATEGORY_DISPLAY_NAME_TO_INTERNAL`。

---

## 5. 提示词模板自定义

### 5.1 system_prompt.md（version_1）

- 角色设定、输出协议（单行/分隔符/大小写/禁词表）、冲突表（§4）、自检清单。
- 关键规则（勿随意改弱）：禁用加权语法 `(tag:1.2)`、禁质量词、禁画师名、禁评级 tag、禁元数据 tag、场景描述 1-4 句。
- 双行 `{{min_tags}}`/`{{max_tags}}` 为 jinja 占位，程序注入。

### 5.2 system_prompt_v2.md（version_2 精修）

- v2 精修用；`--v2-enhance` 或配置 `v2_enhance: true` 启用（v1 额外调用一次 API 按 V2 规则精修）。

### 5.3 user_prompt.jinja（用户提示模板）

- 结构：角色种子 → 抽样 tag 块 → r18 占位符含义 → 约束（subject/ceiling/theme/forced/forbidden）→ 槽位顺序 → 风格方向 → 长度约束 → 角色池指令 → 互动要求 → 多人书写顺序 → 额外要求 → focus → 场景描述规则。
- 修改模板后无需重启；改 `slot_order`、`fill_tag_phrase`、风格方向段可整体调整 LLM 行为。
- 多角色书写顺序、list 结构禁令（`one with...`/`the first...`）已内置于模板，勿删。

### 5.4 后处理（postprocess.py）

- `_ALLOWED_ADDED_TAGS`：允许 LLM 补充的互动/环境短 tag 白名单。
- `_REPLACEMENT_TAGS`：禁词替换映射（`anima规则.txt` Tag 区）。
- `assembler.CONFLICT_RULES`：互斥规则表（视角/身份/服装/动作/细节），改这里可调冲突消解。

---

## 6. 代码级自定义（config.py / 后处理）

`prompt/random_generator/config.py` 是过滤/映射规则的集中地，常用自定义点：

| 常量 | 作用 |
|---|---|
| `EXCLUDED_CATEGORIES` | 直接丢弃的 CSV 大类（如 `二次元角色`、`艺术家`、`无法分类`） |
| `EXCLUDED_SUBCATEGORIES` | 丢弃的 (大类, 子类) 对（如 `成人玩具`、`性器官`、`颜文字`） |
| `EXACT_EXCLUDE_TAGS` | 精确匹配丢弃的 tag（小写空格形式） |
| `EXCLUDE_KEYWORDS` | 子串匹配的噪声关键词（画师/版权元数据） |
| `EXCLUDE_PATTERNS` | 正则排除模式（男性/兽化/性行为/巨乳/阴毛等） |
| `NOISE_META_TAGS` | 介质/噪音 meta tag 黑名单（约 380 项；封面/文字/平台/水印等无画面语义词） |
| `NOISE_META_SUFFIXES` | 后缀命中规则（`" logo"`、`" text"`） |
| `CATEGORY_MAPPINGS` | CSV (大类, 子类) → 内部类别 |
| `TAG_TO_CATEGORY_OVERRIDES` | tag 级类别纠正（如 `nude → clothing_state`） |
| `DEFAULT_COUNT_GENDER_TAGS` | 人数/性别允许的 tag 集合（默认 `{"1girl", "2girls"}`） |
| `PAREN_DISAMBIGUATION_OK` | 括号内常见消歧义词，命中则视为普通 tag 保留 |
| `MIN_TAG_LEN` / `MAX_TAG_LEN` | tag 长度限制 |
| `REQUIRE_NON_EMPTY_CHINESE` | 丢弃无中文翻译的 tag |
| `DEFAULT_SAMPLE_COUNTS` | 内部类别抽样数量默认值（config.py 层） |

- 噪音判定函数 `is_noise_meta_tag(normalized)`：字面命中黑名单或 logo/text 后缀即判定，输入侧已归一化。
- 修改后重跑生成即生效；测试见 `prompt/random_generator/tests/`（`python -m pytest prompt/random_generator/tests`）。

---

## 7. 常见自定义场景速查

| 需求 | 改哪里 |
|---|---|
| 只要可爱系、限制更严 | `max_rating: pg12` + 收紧 `config.EXACT_EXCLUDE_TAGS` |
| 提高人物占比 | `focus_weights.character` 调高 |
| 缩短提示词 | 同时调低 `min_tags` / `max_tags` |
| 去掉某类 tag | `config.EXACT_EXCLUDE_TAGS` / `EXCLUDE_PATTERNS` / `semantic_exclude.yaml` |
| 指定固定角色 | `character_whitelist.pool` 或 `--character-json`（单角色文件） |
| 双人占比 50% | `multi_character.probability: 0.5` |
| 双人全关闭 | `multi_character.enabled: false` |
| 某作品不出场 | `character_pool_series_index.json` 里该 IP `enabled: false` |
| 某作品更常出场 | 该 IP `weight` 调高 |
| 换 API 平台 | 复制 `api_profiles/example.yaml` 为新文件，填 `api_base/model/api_key` |
| 加自定义风格要求 | `extra_requirements` 或 `extra_requirements_pool` |
| r18 禁用某主题 | `r18_topic_control.topics.<主题>.enabled: false` |
| 单人场景禁用某主题 | `r18_topic_control.solo.disabled_topics` |
| 改 LLM 行为 | `system_prompt.md` / `system_prompt_v2.md` / `user_prompt.jinja` |

---

## 附：测试与依赖

```bash
pip install -r prompt/random_generator/requirements.txt   # openai, jinja2, pyyaml, pandas, openpyxl
python -m pytest prompt/random_generator/tests            # 单元测试
```

- 已知：`test_pipeline.py` 有 8 个历史遗留失败（旧 API），与当前 r18 重构无关，未纳入常规回归。
- 本项目基于 BuXinZi 的 [anima-rag-knowledge](https://github.com/BuXinZi/anima-rag-knowledge) 修改而来，遵循 MIT License。
