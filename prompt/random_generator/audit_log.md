# 审计日志（audit_log.jsonl）使用说明

每次真实生成（`python run_generator.py --count N ...`）都会在输出目录追加写入
`audit_log.jsonl`——**每条提示词一行**，记录该提示词的完整生成输入（抽样 tag 及子类、
创意锚点、配置快照）与输出（提示词原文 + 双 hash + 后处理日志）。

## 一、为什么需要它

目标链路：**出图 → 图片元数据 ↔ 日志反查 → 按喜好调配置**。

ComfyUI 出图时会把工作流（含 positive prompt）嵌入 PNG 元数据。通过本日志中的
`tags_sha256` / `sha256`，你可以从任意一张图片反查：

- 这条提示词的**全部抽样输入**（哪个角色、哪类表情、哪个子类配额抽到了什么）；
- 生成时的**配置快照**（sample_counts / subcategory_quotas / default_word_quota /
  focus_weights / 锚点开关）；
- 后处理结果（冲突消解、去重、截断、默认词超标、is_valid）。

积累一批"图片 → 日志"映射后，就能统计"哪些配置/子类产生了你喜欢的图、哪些没产生"，
从而针对性地调整 `generation_config.yaml`。

## 二、字段结构（schema_version: 1）

```json
{
  "schema_version": 1,
  "id": "<seed>-<tags_sha8>",
  "created_at": "2026-02-09T10:00:00+0800",
  "generator": {"name": "anima-random-prompt-generator", "output_file": "output/xxx.jsonl"},
  "params": {
    "seed": 77, "max_rating": "r15", "min_tags": 40, "max_tags": 60,
    "temperature": 0.7, "model": "deepseek-chat", "theme_hint": "",
    "subject_control": "", "extra_requirements": "...", "is_multi_character": false
  },
  "sampled": {
    "expression_reaction": [
      {"tag": "scared", "subcategory": "惊讶恐惧", "source": "knowledge_v1"}, ...
    ],
    "creative_anchor": [{"tag": "...", "subcategory": "", "source": "creative_anchor"}], ...
  },
  "anchors": [{"tag": "tea party in ruins", "anchor_cn": "废墟里的茶会", "anchor_tags": [...]}],
  "quota_snapshot": {
    "sample_counts": {...}, "subcategory_quotas": {...}, "default_word_quota": {...},
    "multi_character": {...}, "focus_weights": {...}, "creative_anchors_enabled": true
  },
  "prompt": {
    "version_1": "1girl, ...",
    "sha256": "<完整原文 hash>",
    "tags_sha256": "<归一化 tag 集合 hash>",
    "tag_count": 55
  },
  "postprocess": {"anti_convergence": {...}, "conflict_log": [...], "is_valid": false, ...},
  "unknown_tags": [...],
  "anchor_retry": false
}
```

### 关键字段

| 字段 | 用途 |
|---|---|
| `prompt.sha256` | 完整 prompt 原文哈希——PNG 元数据中的 positive prompt 与原文**逐字节一致**时可直接匹配 |
| `prompt.tags_sha256` | 归一化 tag 集合哈希（小写、去下划线/括号、剥离 `:权重`、过滤质量词、排序）——**加了质量前缀/调换顺序/改分隔符后仍可匹配** |
| `sampled.*.subcategory` | 每个抽样 tag 的人工子类（如 惊讶恐惧/动态动作/奇幻幻想），用于统计"哪些子类产出你喜欢的图" |
| `quota_snapshot` | 生成时的完整抽样配置，用于对比不同配置批次的效果 |
| `postprocess.anti_convergence` | 默认词超标/构图完整性/表情多样性软校验结果 |

## 三、反查流程（图片 → 日志）

1. **提取图片 positive prompt**：从 ComfyUI 生成的 PNG 元数据中取 positive 文本
   （可用 `anima_prompt_develop/extract_comfyui_metadata/extract.py` 同款 PIL 读取）。
2. **计算 tags_sha256**（与生成器同规则）：
   ```python
   import hashlib, re
   def tags_sha256(prompt: str) -> str:
       NS = {"masterpiece","best quality","good quality","ultra detailed","score 7",
             "score 8","score 9","newest","highres","absurdres","wallpaper","official art",
             "anime screenshot","high quality","safe","sensitive","nsfw","explicit"}
       tags_part = prompt.split(". ")[0] if ". " in prompt else prompt
       def norm(t):
           t = re.sub(r":\d+(\.\d+)?", "", t.lower()).replace("_"," ").replace("("," ").replace(")"," ")
           return " ".join(t.split())
       nt = sorted(norm(t) for t in tags_part.split(",")
                   if t.strip() and norm(t) not in NS)
       return hashlib.sha256("\n".join(nt).encode()).hexdigest()

   import json
   recs = [json.loads(l) for l in open("output/audit_log.jsonl", encoding="utf-8")]
   hit = [r for r in recs if r["prompt"]["tags_sha256"] == tags_sha256(png_prompt)]
   # hit 即该图对应的全部生成输入与配置快照
   ```
3. 若 tags_sha256 未命中，退而尝试 `sha256`（原文一致场景）。

## 四、扩展方式

- 每条记录带 `schema_version`，未来新增字段（如 `image` 回填文件名、`rating` 人工标注）
  直接加键即可，旧记录解析不受影响；
- 读取端请始终用 `record.get("字段", 默认值)` 兜底，兼容旧版本记录。

## 五、健壮性说明

- 每行严格单行 JSON（UTF-8，`ensure_ascii=False`），追加写入 + 逐条 flush；
- 单条审计构建/写入失败只打印警告、跳过该条，不影响提示词主输出；
- **绝不包含 API key** 等敏感信息；
- dry-run 不写审计日志。
