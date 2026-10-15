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

# 基础分类顺序（JSON 中若有新增分类会自动读取并排在后面）
DEFAULT_CATEGORIES = [
    "电脑实用神器", "第三方 App", "iOS 插件", "前端 UI 与动效",
    "数据导出与搬家", "实况照片", "XP 模块", "AI Agent 与工具",
    "福利与自动签到", "壁纸与媒体提取", "网络与代理", "AI Skills",
    "浏览器扩展", "动画图片素材库"
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
    return ["未分类项目"]


def get_all_active_categories(cache_data):
    """从默认列表与当前 JSON 缓存中动态汇总所有已存在的分类"""
    all_cats = list(DEFAULT_CATEGORIES)
    for item in cache_data.values():
        for cat in get_item_categories(item):
            if cat not in all_cats:
                all_cats.append(cat)
    return all_cats


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


def build_prompt(full_name, desc, active_categories):
    categories_str = ", ".join(active_categories)
    return f"""你是一个极其严谨的 GitHub 仓库分类器。请根据仓库信息完成分类和一句话总结。

仓库名称: {full_name}
官方描述: {desc or '无'}

【当前已有文件夹】
[{categories_str}]

【严格分类铁律（零凑合原则）】
1. 严格字面边界：检查该项目是否 100% 契合【当前已有文件夹】的字面专业领域。
   - 注意：“电脑实用神器”仅限 Windows/Mac 桌面端运行的实用软件程序，绝不是万能杂物间！
   - 注意：“第三方 App”仅限手机或跨平台客户端应用！
2. 严禁强行凑数：如果该项目属于现有文件夹未覆盖的新领域（例如：美食菜谱、生活指南、游戏 Mod、电子书、硬件固件、图标素材、学术教程等），**严禁塞进任何一个已有文件夹**！
3. 主动新建文件夹：只要与现有文件夹不是 100% 领域吻合，必须根据它的真实属性，主动新建 1 个精准、通俗的文件夹名称（4 到 7 个汉字，不带标点）。

【总结规则】
用一句话（15到25个汉字以内）讲清楚核心用途。必须用通俗大白话，不带技术黑话，普通人一眼看懂。

请直接以严格 JSON 格式输出：
{{"categories": ["分类名称"], "summary": "通俗大白话一句话说明"}}
"""


def request_gemini_api(model_name, prompt):
    if not GEMINI_API_KEY:
        raise ValueError("缺少 GEMINI_API_KEY 环境变量")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={GEMINI_API_KEY}"
    )

    gen_config = {
        "temperature": 0.1,
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


def summarize_with_tiered_chain(full_name, desc, active_categories):
    prompt = build_prompt(full_name, desc, active_categories)

    for idx, model in enumerate(MODELS_CHAIN):
        try:
            data = request_gemini_api(model, prompt)
            raw_cats = data.get("categories") or [data.get("category", "")]
            if isinstance(raw_cats, str):
                raw_cats = [raw_cats]
            cats = [c.strip() for c in raw_cats if c.strip()]
            summary = str(data.get("summary", "")).strip()

            if cats and summary:
                return cats, summary
        except Exception as e:
            print(f"⚠️ [{model}] 调用失败: {e}")
            if idx < len(MODELS_CHAIN) - 1:
                time.sleep(1)

    # 如果所有模型全部调用失败，返回 None，绝不乱塞假分类污染缓存
    return None, None


def render_compact_readme(cache_data):
    """排版：顶部小人 200px 居中、标题匹配 32px 星星、导航宽松靠左"""
    total_count = len(cache_data)
    all_categories = get_all_active_categories(cache_data)

    # 1. 顶部小人：宽度 200px 居中
    content = '<p align="center">\n'
    content += '  <img src="./image/Frieren.gif" width="240" alt="Frieren" />\n'
    content += '</p>\n\n'

    # 2. 标题区：使用本地 Star.gif，尺寸 32x32 与大标题字号齐平
    star_path = get_star_gif_path()
    content += f'# <img src="{star_path}" width="32" height="32" valign="middle" alt="Star" /> Star Notes\n\n'
    content += f'> 自动同步于 GitHub Actions · 共收录 **{total_count}** 个项目\n\n'

    # 3. 快速导航：纯左对齐，每行 2 项，宽松行距
    content += "### 快速导航\n\n"

    valid_categories = []
    toc_links = []

    for cat in all_categories:
        count = sum(1 for item in cache_data.values() if cat in get_item_categories(item))
        if count > 0:
            idx = len(valid_categories)
            valid_categories.append(cat)
            toc_links.append(f'[{cat} ({count})](#cat-{idx})')

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

    # 铁门逻辑：只要已经在 stars_cache.json 里的老项目，绝对跳过不碰！
    new_repos = [repo for full_name, repo in remote_dict.items() if full_name not in cache]

    if new_repos:
        print(f"检测到 {len(new_repos)} 个新增项目，开始处理...")
        new_repos.reverse()
        for repo in new_repos:
            full_name = repo["full_name"]
            desc = repo.get("description", "")
            active_cats = get_all_active_categories(cache)
            cats, summary = summarize_with_tiered_chain(full_name, desc, active_cats)

            # 只有当 AI 成功返回有效分类时才写入缓存，杜绝网络失败时乱塞默认分类
            if cats and summary:
                cache[full_name] = {
                    "name": repo.get("name", full_name.split("/")[-1]),
                    "full_name": full_name,
                    "html_url": repo.get("html_url", ""),
                    "categories": cats,
                    "summary": summary
                }
            else:
                print(f"❌ [{full_name}] 所有模型均未能返回有效分类，本次跳过，留待下次重试。")
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
