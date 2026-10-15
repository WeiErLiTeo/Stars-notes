import os
import requests
import json
import re
import time

# ================= 核心配置 =================
GITHUB_USERNAME = "WeiErLiTeo"
CACHE_FILE = "stars_cache.json"
README_FILE = "README.md"
STAR_SVG_FILE = "star.svg"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GH_TOKEN = os.environ.get("GITHUB_TOKEN")

# 严格采用 3.0+ 家族模型梯队
MODELS_CHAIN = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite"
]

# 预设的 13 个基础分类
DEFAULT_CATEGORIES = [
    "电脑实用神器", "第三方 App", "iOS 插件", "前端 UI 与动效",
    "数据导出与搬家", "实况照片", "XP 模块", "AI Agent 与工具",
    "福利与自动签到", "壁纸与媒体提取", "网络与代理", "AI Skills", "浏览器扩展"
]

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GH_TOKEN:
    HEADERS["Authorization"] = f"token {GH_TOKEN}"


def ensure_star_svg():
    """确保仓库中存在动态星星 SVG 文件（若不存在则自动生成）"""
    if os.path.exists(STAR_SVG_FILE):
        return

    svg_content = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100%" height="100%">
  <defs>
    <linearGradient id="starGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#FFDF00" />
      <stop offset="100%" stop-color="#F59E0B" />
    </linearGradient>
  </defs>
  <style>
    @keyframes starPulse {
      0%, 100% { transform: scale(1); transform-origin: 50px 50px; opacity: 0.92; }
      50% { transform: scale(1.08); transform-origin: 50px 50px; opacity: 1; }
    }
    @keyframes starSparkleA {
      0%, 100% { opacity: 0.25; transform: scale(0.6); transform-origin: 18px 16px; }
      50% { opacity: 1; transform: scale(1.15); transform-origin: 18px 16px; }
    }
    @keyframes starSparkleB {
      0%, 100% { opacity: 0.25; transform: scale(0.6); transform-origin: 82px 24px; }
      50% { opacity: 1; transform: scale(1.15); transform-origin: 82px 24px; }
    }
    .main-star {
      animation: starPulse 2.4s ease-in-out infinite;
    }
    .sparkle-a {
      animation: starSparkleA 1.8s ease-in-out infinite;
    }
    .sparkle-b {
      animation: starSparkleB 2.2s ease-in-out infinite 0.8s;
    }
  </style>
  <g class="main-star">
    <polygon points="50,6 64,36 97,38 72,62 80,94 50,77 20,94 28,62 3,38 36,36" fill="url(#starGrad)" />
  </g>
  <g class="sparkle-a">
    <polygon points="18,10 20,14 24,16 20,18 18,22 16,18 12,16 16,14" fill="#FFF9C4" />
  </g>
  <g class="sparkle-b">
    <polygon points="82,18 84,22 88,24 84,26 82,30 80,26 76,24 80,22" fill="#FFF9C4" />
  </g>
</svg>"""

    with open(STAR_SVG_FILE, "w", encoding="utf-8") as f:
        f.write(svg_content)


def fetch_all_starred():
    """全量分页拉取所有 Starred 仓库"""
    starred = []
    page = 1

    while True:
        url = (
            f"https://api.github.com/users/{GITHUB_USERNAME}"
            f"/starred?page={page}&per_page=100"
        )

        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            print(f"拉取 Starred 时网络请求失败: {e}")
            break

        if resp.status_code != 200:
            print(f"拉取 Starred 失败: HTTP {resp.status_code}")
            print(resp.text[:500])
            break

        try:
            data = resp.json()
        except ValueError:
            print("拉取 Starred 失败：GitHub 返回的不是有效 JSON")
            break

        if not data:
            break

        starred.extend(data)

        if len(data) < 100:
            break

        page += 1

    return starred


def build_prompt(full_name, desc):
    """构建 Gemini 分类和总结提示词"""
    categories_str = ", ".join(DEFAULT_CATEGORIES)

    return f"""你是一个通俗软件归类助手。请根据仓库信息完成分类和总结。

仓库名称: {full_name}
官方描述: {desc or '无'}

【分类规则】
1. 优先从以下预设分类中挑选一个最匹配的：
[{categories_str}]
2. 如果该项目确实与以上所有分类完全不符，允许自主提炼一个全新分类（必须为 4 到 8 个汉字，不要带标点）。

【总结规则】
用一句话（15到25个汉字以内）讲清楚核心用途。必须用通俗大白话，不带技术开发黑话，让普通人一眼看懂用途。

请直接以严格 JSON 格式输出：
{{"category": "分类名", "summary": "通俗大白话一句话说明"}}
"""


def request_gemini_api(model_name, prompt):
    """请求指定的 Gemini 模型"""
    if not GEMINI_API_KEY:
        raise ValueError("缺少 GEMINI_API_KEY 环境变量")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={GEMINI_API_KEY}"
    )

    gen_config = {
        "temperature": 0.2,
        "responseMimeType": "application/json"
    }

    if "3.8-flash" in model_name or "3.6-flash" in model_name:
        gen_config["thinkingConfig"] = {"thinkingLevel": "LOW"}

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": gen_config
    }

    resp = requests.post(url, json=payload, timeout=20)

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} - {resp.text[:1000]}")

    res_data = resp.json()

    try:
        raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(
            f"Gemini 返回内容格式异常：{json.dumps(res_data, ensure_ascii=False)[:1000]}"
        ) from e

    clean_json = re.sub(r"```(?:json)?|```", "", raw_text).strip()

    try:
        result = json.loads(clean_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini 返回的内容不是有效 JSON：{raw_text[:500]}") from e

    return result


def summarize_with_tiered_chain(full_name, desc):
    """按模型梯队依次尝试，前一个失败则切换下一个"""
    prompt = build_prompt(full_name, desc)

    for idx, model in enumerate(MODELS_CHAIN):
        try:
            data = request_gemini_api(model, prompt)

            cat = str(data.get("category", "")).strip() or "电脑实用神器"
            summary = (
                str(data.get("summary", "")).strip()
                or (desc[:30] if desc else "暂无说明")
            )

            return cat, summary

        except Exception as e:
            print(f"⚠️ [{model}] 调用失败: {e}")

            if idx < len(MODELS_CHAIN) - 1:
                time.sleep(1)

    return "电脑实用神器", (desc[:30] if desc else "暂无说明")


def render_compact_readme(cache_data):
    """生成居中小人、左对齐标题与动态星星、移动端优化导航"""
    total_count = len(cache_data)

    all_categories = list(DEFAULT_CATEGORIES)
    for item in cache_data.values():
        cat = item.get("category")
        if cat and cat not in all_categories:
            all_categories.append(cat)

    # 1. 顶部小人：单独居中，宽度适度调优为 240px，避免撑满两端
    content = '<p align="center">\n'
    content += '  <img src="./image/Frieren.gif" width="240" alt="Frieren" />\n'
    content += '</p>\n\n'

    # 2. 标题区：左对齐，嵌入动态星星
    content += '# <img src="./star.svg" width="28" height="28" valign="middle" alt="Star" /> Star Notes\n\n'
    content += f'> 自动同步于 GitHub Actions · 共收录 **{total_count}** 个项目\n\n'

    # 3. 快速导航：左对齐，每行 2 个分类标签
    content += "### 快速导航\n\n"

    valid_categories = []
    toc_links = []

    for cat in all_categories:
        count = sum(
            1 for item in cache_data.values()
            if item.get("category") == cat
        )

        if count > 0:
            idx = len(valid_categories)
            valid_categories.append(cat)
            toc_links.append(f'[`{cat} ({count})`](#cat-{idx})')

    separator = " &nbsp;·&nbsp; "
    rows = [separator.join(toc_links[i:i + 2]) for i in range(0, len(toc_links), 2)]
    content += "<br>\n".join(rows) + "\n\n---\n\n"

    # 4. 正文分类详情：标准左对齐
    for idx, cat in enumerate(valid_categories):
        matched = [
            item for item in cache_data.values()
            if item.get("category") == cat
        ]

        content += f'<span id="cat-{idx}"></span>\n\n'
        content += f"## {cat}\n\n"

        for item in matched:
            name = item.get("name", "未命名仓库")
            html_url = item.get("html_url", "#")
            summary = item.get("summary", "暂无说明")

            content += f"- [**{name}**]({html_url}) — {summary}\n"

        content += "\n"

    # 5. 底部计数器：居中
    content += "---\n\n"
    content += '<p align="center">\n'
    content += (
        '  <img src="https://count.getloli.com/'
        'get/@WeiErLiTeo-stars-notes?theme=rule34" '
        'alt="Moe Counter" />\n'
    )
    content += '</p>\n'

    return content


def main():
    """同步 Starred 仓库、更新缓存并生成 README"""
    if not GEMINI_API_KEY:
        raise ValueError("缺少 GEMINI_API_KEY 环境变量")

    ensure_star_svg()

    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)

            if not isinstance(cache, dict):
                print("⚠️ 缓存格式不正确，将重新创建缓存")
                cache = {}

        except (OSError, json.JSONDecodeError) as e:
            print(f"⚠️ 读取缓存失败，将重新创建缓存: {e}")
            cache = {}

    starred_list = fetch_all_starred()

    remote_dict = {
        repo["full_name"]: repo
        for repo in starred_list
        if repo.get("full_name")
    }

    # 移除已取消收藏的项目
    for cached_name in list(cache.keys()):
        if cached_name not in remote_dict:
            del cache[cached_name]

    # 增量分析新项目
    new_repos = [
        repo
        for full_name, repo in remote_dict.items()
        if full_name not in cache
    ]

    if new_repos:
        new_repos.reverse()

        for repo in new_repos:
            full_name = repo["full_name"]
            desc = repo.get("description", "")

            cat, summary = summarize_with_tiered_chain(full_name, desc)

            cache[full_name] = {
                "name": repo.get("name", full_name.split("/")[-1]),
                "full_name": full_name,
                "html_url": repo.get("html_url", ""),
                "category": cat,
                "summary": summary
            }

            time.sleep(3)

    readme_content = render_compact_readme(cache)

    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(readme_content)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"同步完毕，共收录 {len(cache)} 个项目。")


if __name__ == "__main__":
    main()
