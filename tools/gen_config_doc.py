#!/usr/bin/env python3
"""生成配置文档 HTML（可搜索）。

用法：python tools/gen_config_doc.py
产物：docs/配置文档.html
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from prompt.random_generator import config, yaml_comments
from prompt.random_generator.gui_qt import i18n

OUT = ROOT / "docs" / "配置文档.html"


def _load_cfg() -> dict:
    import yaml

    with config.GENERATION_CONFIG_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _fmt_value(v) -> str:
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)[:120] + ("…" if len(json.dumps(v, ensure_ascii=False)) > 120 else "")
    if isinstance(v, list):
        if len(v) > 3:
            return f"[{len(v)} 项] " + json.dumps(v[:2], ensure_ascii=False) + " …"
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return "是" if v else "否"
    if v is None:
        return "（空）"
    return str(v)


def _type_label(v) -> str:
    if isinstance(v, bool):
        return "开关"
    if isinstance(v, int):
        return "数字"
    if isinstance(v, float):
        return "小数"
    if isinstance(v, str):
        return "文本"
    if isinstance(v, dict):
        return "分组"
    if isinstance(v, list):
        return "列表"
    return "其他"


def main() -> int:
    gen_cfg = _load_cfg()
    help_map = yaml_comments.build_help_map(config.GENERATION_CONFIG_FILE)

    # 收集所有条目
    entries: list[dict] = []

    def walk(data, prefix=""):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            help_text = (help_map.get(p, {}).get("help") or help_map.get(p, {}).get("inline") or "")
            entries.append({
                "path": p,
                "key": k,
                "value": v,
                "help": help_text,
                "cn": i18n.KEY_NAMES.get(k) or i18n.FIELD_NAMES.get(k, ""),
                "type": _type_label(v),
                "fmt": _fmt_value(v),
            })
            if isinstance(v, dict):
                walk(v, p)

    walk(gen_cfg)

    # 章节分组（与 GUI 高级页一致）
    sections = [
        ("基础设置", ["max_rating", "min_tags", "max_tags", "output_dir", "extra_requirements", "creative_anchors", "min_r18_tags_per_sample"]),
        ("抽样数量", ["sample_counts", "r18_sample_counts"]),
        ("子类配额", ["subcategory_quotas"]),
        ("反趋同词配额", ["default_word_quota"]),
        ("生成侧重点", ["focus_weights", "r18_focus_weights"]),
        ("多角色", ["multi_character"]),
        ("r18 控制", ["r18_topic_control", "r18_instructions"]),
        ("API 参数", ["deepseek"]),
        ("额外要求池", ["extra_requirements_pool"]),
        ("角色池", ["character_pool", "character_whitelist"]),
        ("类别白名单", ["category_whitelists"]),
    ]

    # 构建 HTML 表格行（带 data-search 属性供 JS 过滤）
    def rows_for(keys):
        html = []
        for key in keys:
            for e in entries:
                if e["path"] == key or e["path"].startswith(key + "."):
                    search_text = " ".join([e["cn"], e["key"], e["path"], e["help"], e["fmt"]])
                    html.append(f"""
                    <tr class="cfg-row" data-search="{search_text}">
                        <td class="cn">{e['cn'] or e['key']}</td>
                        <td class="key">{e['path']}</td>
                        <td class="type">{e['type']}</td>
                        <td class="val"><code>{e['fmt']}</code></td>
                        <td class="help">{e['help']}</td>
                    </tr>""")
        return "\n".join(html)

    section_html = ""
    for title, keys in sections:
        section_html += f"""
        <section class="cfg-section" id="sec-{keys[0]}" data-section="{title}">
            <h2>▍{title}</h2>
            <table class="cfg-table">
                <thead><tr><th>配置项</th><th>配置键</th><th>类型</th><th>默认值</th><th>说明与效果</th></tr></thead>
                <tbody>{rows_for(keys)}</tbody>
            </table>
        </section>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anima 随机提示词生成器 — 配置文档</title>
<style>
:root {{
    --bg: #f4f6f9; --card: #fff; --border: #e0e4e8; --accent: #007bff;
    --text: #2c3238; --muted: #7a828a; --code-bg: #f0f4f8;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; background: var(--bg); color: var(--text); line-height: 1.7; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
header {{ background: linear-gradient(135deg, #007bff, #00c6ff); color: #fff; padding: 40px 20px; text-align: center; border-radius: 0 0 16px 16px; }}
header h1 {{ font-size: 28px; margin-bottom: 8px; }}
header p {{ opacity: .9; font-size: 15px; }}
/* 搜索框 */
.search-wrap {{ max-width: 700px; margin: -24px auto 24px; padding: 0 20px; position: relative; z-index: 5; }}
#search {{ width: 100%; padding: 14px 20px; font-size: 15px; border: 2px solid var(--accent); border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,.1); outline: none; }}
#search:focus {{ box-shadow: 0 4px 20px rgba(0,123,255,.25); }}
.search-hint {{ text-align: center; color: var(--muted); font-size: 12px; margin-top: 6px; }}
/* 快速开始 */
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 16px 0; }}
.card h2 {{ color: var(--accent); margin-bottom: 12px; font-size: 20px; }}
.steps {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; }}
.step {{ background: var(--code-bg); border-radius: 10px; padding: 16px; }}
.step .num {{ display: inline-block; background: var(--accent); color: #fff; width: 26px; height: 26px; border-radius: 50%; text-align: center; line-height: 26px; font-weight: bold; margin-bottom: 8px; }}
.step h3 {{ font-size: 15px; margin-bottom: 6px; }}
.step p {{ font-size: 13px; color: var(--muted); }}
/* 截图 */
.shots {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }}
.shot {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 10px; text-align: center; }}
.shot img {{ max-width: 100%; border-radius: 8px; border: 1px solid var(--border); }}
.shot p {{ font-size: 13px; color: var(--muted); margin-top: 8px; }}
/* 章节导航 */
.nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }}
.nav a {{ background: var(--card); border: 1px solid var(--border); border-radius: 20px; padding: 6px 14px; text-decoration: none; color: var(--text); font-size: 13px; transition: all .2s; }}
.nav a:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
/* 配置表 */
.cfg-section {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; margin: 20px 0; }}
.cfg-section h2 {{ color: var(--accent); margin-bottom: 12px; font-size: 18px; border-bottom: 2px solid var(--border); padding-bottom: 8px; }}
.cfg-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.cfg-table th {{ background: var(--code-bg); text-align: left; padding: 10px 12px; position: sticky; top: 0; }}
.cfg-table td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
.cfg-table tr:hover td {{ background: #f0f7ff; }}
.cfg-table .cn {{ font-weight: bold; white-space: nowrap; }}
.cfg-table .key {{ color: var(--muted); font-family: Consolas, monospace; font-size: 12px; white-space: nowrap; }}
.cfg-table .type {{ color: var(--muted); font-size: 12px; text-align: center; }}
.cfg-table .val code {{ background: var(--code-bg); padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
.cfg-table .help {{ color: var(--text); }}
/* 隐藏未匹配 */
.hidden {{ display: none !important; }}
/* 示例 */
.example {{ background: var(--code-bg); border-left: 4px solid var(--accent); border-radius: 0 8px 8px 0; padding: 12px 16px; margin: 10px 0; font-size: 13px; }}
.example b {{ color: var(--accent); }}
footer {{ text-align: center; color: var(--muted); font-size: 12px; padding: 30px 0; }}
/* 搜索高亮 */
mark {{ background: #ffe08a; padding: 0 2px; border-radius: 2px; }}
</style>
</head>
<body>
<header>
    <h1>🎨 Anima 随机提示词生成器 · 配置文档</h1>
    <p>面向零基础用户的完整配置指南 —— 搜索、阅读、直接使用</p>
</header>

<div class="search-wrap">
    <input type="text" id="search" placeholder="🔍 搜索配置项 / 说明 / 效果…（如：抽样数量、max_rating、擦边、温度）" autocomplete="off">
    <div class="search-hint">输入关键词实时过滤下方配置表，支持中文名、英文键、说明内容</div>
</div>

<div class="container">

<div class="card">
    <h2>🚀 快速开始（3 步）</h2>
    <div class="steps">
        <div class="step"><span class="num">1</span><h3>打开软件</h3><p>双击 <code>AnimaPromptGenerator.exe</code>，或源码运行 <code>python anima_gui_qt.py</code></p></div>
        <div class="step"><span class="num">2</span><h3>选择模式</h3><p>有 API Key →「生成」页填写并生成；没有 →「无 API 模式」生成模板复制给网页 LLM</p></div>
        <div class="step"><span class="num">3</span><h3>调整喜好</h3><p>「高级」页左侧章节按需修改，悬停任意配置项可看说明；改完点「保存设置」</p></div>
    </div>
</div>

<div class="card">
    <h2>🖼️ 界面一览</h2>
    <div class="shots">
        <div class="shot"><img src="tab0.png" alt="生成页"><p>① 生成页：批量生成提示词</p></div>
        <div class="shot"><img src="tab1.png" alt="无API模式"><p>② 无 API 模式：复制模板给网页 LLM</p></div>
        <div class="shot"><img src="tab2.png" alt="API设置"><p>③ API 设置：OpenAI 兼容接口</p></div>
        <div class="shot"><img src="tab3.png" alt="高级配置"><p>④ 高级：全配置可视化编辑</p></div>
        <div class="shot"><img src="tab4.png" alt="配置预设"><p>⑤ 配置：多预设保存/切换</p></div>
        <div class="shot"><img src="tab5.png" alt="日志"><p>⑥ 日志：运行记录与输出</p></div>
        <div class="shot"><img src="nomodel_result.png" alt="无API结果"><p>⑦ 无 API 模式生成结果（代码框）</p></div>
    </div>
</div>

<div class="card">
    <h2>🧭 配置章节导航</h2>
    <div class="nav">
        <a href="#sec-max_rating">基础设置</a>
        <a href="#sec-sample_counts">抽样数量</a>
        <a href="#sec-subcategory_quotas">子类配额</a>
        <a href="#sec-default_word_quota">反趋同词配额</a>
        <a href="#sec-focus_weights">生成侧重点</a>
        <a href="#sec-multi_character">多角色</a>
        <a href="#sec-r18_topic_control">r18 控制</a>
        <a href="#sec-deepseek">API 参数</a>
        <a href="#sec-extra_requirements_pool">额外要求池</a>
        <a href="#sec-character_pool">角色池</a>
        <a href="#sec-category_whitelists">类别白名单</a>
    </div>
</div>

<div class="card">
    <h2>💡 常见调整与效果示例</h2>
    <div class="example"><b>想让画面更丰富</b> → 高级页「抽样数量」把 <code>appearance</code>（外貌）从 20 调到 30，更多外貌 tag 供 LLM 选择</div>
    <div class="example"><b>想让角色出现频率更高</b> → 「多角色」把 <code>probability</code> 从 0.25 调到 0.5，约一半样本变成双人</div>
    <div class="example"><b>不想看到某类内容</b> → 「子类配额」把对应子类 <code>max</code> 设为 0，完全不抽样该类 tag</div>
    <div class="example"><b>画面太套路</b> → 「反趋同词配额」把 soft lighting / cherry blossom 等词配额调低或设 0</div>
    <div class="example"><b>输出更稳定</b> → 「API 参数」把 <code>temperature</code> 从 0.7 调到 0.5</div>
    <div class="example"><b>批量生成更多</b> → 「生成」页数量填 1000+，断点续存自动跳过已完成条数</div>
</div>

{section_html}

<footer>Anima 随机提示词生成器 · 配置文档 · 搜索即所得</footer>
</div>

<script>
(function () {{
    const input = document.getElementById('search');
    const rows = document.querySelectorAll('.cfg-row');
    const sections = document.querySelectorAll('.cfg-section');

    input.addEventListener('input', function () {{
        const q = this.value.trim().toLowerCase();
        let visibleCount = 0;
        rows.forEach(function (row) {{
            const hay = (row.dataset.search || '').toLowerCase();
            const match = !q || hay.includes(q);
            row.classList.toggle('hidden', !match);
            if (match) visibleCount++;
        }});
        // 章节标题根据其行是否可见
        sections.forEach(function (sec) {{
            const secRows = sec.querySelectorAll('.cfg-row');
            let anyVisible = false;
            secRows.forEach(function (r) {{ if (!r.classList.contains('hidden')) anyVisible = true; }});
            sec.classList.toggle('hidden', !anyVisible && q !== '');
        }});
        document.title = q ? `搜索「${{q}}」— 配置文档` : 'Anima 随机提示词生成器 — 配置文档';
    }});
}})();
</script>
</body>
</html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT}（{len(html)//1024} KB，{len(entries)} 项配置）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
