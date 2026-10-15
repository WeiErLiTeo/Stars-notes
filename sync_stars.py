import os
import requests
import json
import re
import time

# ================= 核心配置 =================
GITHUB_USERNAME = "WeiErLiTeo"
CACHE_FILE = "stars_cache.json"
README_FILE = "README.md"
IMAGE_DIR = "image"

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

# 预设的基础 13 个分类（按优先级排序）
DEFAULT_CATEGORIES = [
    "电脑实用神器", "第三方 App", "iOS 插件", "前端 UI 与动效",
    "数据导出与搬家", "实况照片", "XP 模块", "AI Agent 与工具",
    "福利与自动签到", "壁纸与媒体提取", "网络与代理", "AI Skills", "浏览器扩展"
]

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GH_TOKEN:
    HEADERS["Authorization"] = f"token {GH_TOKEN}"


def get_star_gif_path():
    """兼容大小写：优先检测 Star.gif，其次匹配 star.gif"""
    if os.path.exists(os.path.join(IMAGE_DIR, "Star.gif")):
        return "./image/Star.gif"
    if os.path.exists(os.path.join(IMAGE_DIR, "star.gif")):
        return "./image/star.gif"
    return "./image/Star.gif"


def get_item_categories(item):
    """统一兼容多分类列表与旧的单分类格式"""
    if "categories" in item and isinstance(item["categories"], list):
        return [c.strip() for c in item["categories"] if c.strip()]
    if "category" in item and item["category"]:
        return [item["category"].strip()]
    return ["电脑实用神器"]


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
            break

        try:
            data = resp.json()
        except ValueError:
            break

        if not data:
            break

        starred.extend(data)
        if len(data) < 100:
            break
        page += 1

    return starred


def build_prompt(full_name, desc):
    categories_str = ", ".join(DEFAULT_CATEGORIES)
    return f"""你是一个通俗软件归类助手。请根据仓库信息完成分类和总结。

仓库名称: {full_name}
官方描述: {desc or '无'}

【分类规则】
1. 优先从以下预设分类中挑选 1 到 2 个最匹配的分类（可以多选，若跨界可填 2 个）：
[{categories_str}]
2. 如果该项目确实与以上所有分类完全不符，允许提炼 1 个全新分类（4 到 8 个汉字）。

【总结规则】
用一句话（15到25个汉字以内）讲清楚核心用途。必须用通俗大白话，不带技术黑话，普通人一眼看懂。

请直接以严格 JSON 格式输出：
{{"categories": ["分类1", "分类2"], "summary": "通俗大白话一句话说明"}}
"""


def request_gemini_api(model_name, prompt):
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
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config
    }

    resp = requests.post(url, json=payload, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} - {resp.text[:300]}")

    res_data = resp.json()
    raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"]
    clean_json = re.sub(r"```(?:json)?|```", "", raw_text).strip()
    return json.loads(clean_json)


def summarize_with_tiered_chain(full_name, desc):
    prompt = build_prompt(full_name, desc)

    for idx, model in enumerate(MODELS_CHAIN):
        try:
            data = request_gemini_api(model, prompt)
            raw_cats = data.get("categories") or [data.get("category", "电脑实用神器")]
            if isinstance(raw_cats, str):
                raw_cats = [raw_cats]
            cats = [c.strip() for c in raw_cats if c.strip()] or ["电脑实用神器"]
            summary = str(data.get("summary", "")).strip() or (desc[:30] if desc else "暂无说明")
            return cats, summary
        except Exception as e:
            print(f"⚠️ [{model}] 调用失败: {e}")
            if idx < len(MODELS_CHAIN) - 1:
                time.sleep(1)

    return ["电脑实用神器"], (desc[:30] if desc else "暂无说明")


def render_compact_readme(cache_data):
    """排版：顶部小人微调为 200px 居中、标题匹配 32px 星星、导航宽松靠左"""
    total_count = len(cache_data)

    # 动态汇聚所有分类
    all_categories = list(DEFAULT_CATEGORIES)
    for item in cache_data.values():
        for cat in get_item_categories(item):
            if cat not in all_categories:
                all_categories.append(cat)

    # 1. 顶部小人：宽度微调至 200px，保留呼吸感
    content = '<p align="center">\n'
    content += '  <img src="./image/Frieren.gif" width="200" alt="Frieren" />\n'
    content += '</p>\n\n'

    # 2. 标题区：使用本地 Star.gif，尺寸设置为 32x32 与大标题字号齐平
    star_path = get_star_gif_path()
    content += f'# <img src="{star_path}" width="32" height="32" valign="middle" alt="Star" /> Star Notes\n\n'
    content += f'> 自动同步于 GitHub Actions · 共收录 **{total_count}** 个项目\n\n'

    # 3. 快速导航：纯左对齐，每行 2 项，行距与字距均做适度拉宽
    content += "### 快速导航\n\n"

    valid_categories = []
    toc_links = []

    for cat in all_categories:
        count = sum(1 for item in cache_data.values() if cat in get_item_categories(item))
        if count > 0:
            idx = len(valid_categories)
            valid_categories.append(cat)
            toc_links.append(f'[{cat} ({count})](#cat-{idx})')

    # 水平拉开间距，竖向使用两段换行拉开行高，显得松散舒适
    separator = " &emsp;·&emsp; "
    rows = [separator.join(toc_links[i:i + 2]) for i in range(0, len(toc_links), 2)]
    content += "<br><br>\n".join(rows) + "\n\n---\n\n"

    # 4. 正文分类列表：多标签对应呈现
    for idx, cat in enumerate(valid_categories):
        matched = [item for item in cache_data.values() if cat in get_item_categories(item)]

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
    if not GEMINI_API_KEY:
        raise ValueError("缺少 GEMINI_API_KEY 环境变量")

    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if not isinstance(cache, dict):
                cache = {}
        except Exception:
            cache = {}

    starred_list = fetch_all_starred()
    remote_dict = {repo["full_name"]: repo for repo in starred_list if repo.get("full_name")}

    # 移除已取消收藏的项目
    for cached_name in list(cache.keys()):
        if cached_name not in remote_dict:
            del cache[cached_name]

    # 仅对未存在于缓存中的新项目调用 AI
    new_repos = [repo for full_name, repo in remote_dict.items() if full_name not in cache]

    if new_repos:
        print(f"检测到 {len(new_repos)} 个新增项目，开始处理...")
        new_repos.reverse()
        for repo in new_repos:
            full_name = repo["full_name"]
            desc = repo.get("description", "")
            cats, summary = summarize_with_tiered_chain(full_name, desc)

            cache[full_name] = {
                "name": repo.get("name", full_name.split("/")[-1]),
                "full_name": full_name,
                "html_url": repo.get("html_url", ""),
                "categories": cats,
                "summary": summary
            }
            time.sleep(3)

    # 生成 README 并持久化缓存
    readme_content = render_compact_readme(cache)
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(readme_content)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"更新完成，当前有效收录 {len(cache)} 个项目。")


if __name__ == "__main__":
    main()
