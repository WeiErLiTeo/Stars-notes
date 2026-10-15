import os
import requests
import json
import re
import time

# ================= 核心配置 =================
GITHUB_USERNAME = "WeiErLiTeo"  # 你的 GitHub 账户名
CACHE_FILE = "stars_cache.json"
README_FILE = "README.md"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GH_TOKEN = os.environ.get("GITHUB_TOKEN")

# 严格采用 3.0+ 家族：主力 Flash 优先，Lite 最后垫底
MODELS_CHAIN = [
    "gemini-3.8-flash",       # 1. 旗舰主力 Flash（归类与理解最强）
    "gemini-3.6-flash",       # 2. 备用高配 Flash
    "gemini-3.5-flash",       # 3. 经典通用 Flash
    "gemini-3.1-flash-lite",  # 4. 轻量过渡 Lite
    "gemini-3.5-flash-lite"   # 5. 终极兜底 Lite（高吞吐保底）
]

# 预设的 13 个基础分类（按优先级排序）
DEFAULT_CATEGORIES = [
    "电脑实用神器", "第三方 App", "iOS 插件", "前端 UI 与动效",
    "数据导出与搬家", "实况照片", "XP 模块", "AI Agent 与工具",
    "福利与自动签到", "壁纸与媒体提取", "网络与代理", "AI Skills", "浏览器扩展"
]

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GH_TOKEN:
    HEADERS["Authorization"] = f"token {GH_TOKEN}"

def fetch_all_starred():
    """全量分页拉取所有 Starred 仓库"""
    starred = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/starred?page={page}&per_page=100"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"拉取 Starred 失败: HTTP {resp.status_code}")
            break
        data = resp.json()
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
1. 优先从以下预设分类中挑选一个最匹配的：
[{categories_str}]
2. 如果该项目确实与以上所有分类完全不符（例如属于“固件刷机”、“音视频后期”、“嵌入式硬件”等全新领域），允许自主提炼一个极其精炼的全新分类名称（必须为 4 到 8 个汉字，不要带任何标点）。

【总结规则】
用一句话（15到25个汉字以内）讲清楚核心用途。必须用通俗大白话，不带技术开发黑话，让普通人一眼看懂用途。

请直接以严格 JSON 格式输出，不要包含任何多余文本或 markdown 标签：
{{"category": "分类名", "summary": "通俗大白话一句话说明"}}
"""

def request_gemini_api(model_name, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    
    gen_config = {
        "temperature": 0.2,
        "responseMimeType": "application/json"
    }
    # 限制推理深度，避免消耗多余时间与 token
    if "3.8-flash" in model_name or "3.6-flash" in model_name:
        gen_config["thinkingConfig"] = {"thinkingLevel": "LOW"}

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config
    }
    resp = requests.post(url, json=payload, timeout=20)
    if resp.status_code == 200:
        res_data = resp.json()
        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json|```', '', raw_text).strip()
        return json.loads(clean_json)
    raise RuntimeError(f"HTTP {resp.status_code} - {resp.text}")

def summarize_with_tiered_chain(full_name, desc):
    """五级降级轮询机制"""
    prompt = build_prompt(full_name, desc)
    for idx, model in enumerate(MODELS_CHAIN):
        try:
            data = request_gemini_api(model, prompt)
            cat = data.get("category", "").strip() or "电脑实用神器"
            summary = data.get("summary", "").strip() or (desc[:30] if desc else "暂无说明")
            return cat, summary
        except Exception as e:
            print(f"⚠️ [{model}] 调用失败: {e}")
            if idx < len(MODELS_CHAIN) - 1:
                time.sleep(1)
    return "电脑实用神器", (desc[:30] if desc else "暂无说明")

def render_compact_readme(cache_data):
    """按照规范生成紧凑、带导航、底部带芙莉莲与计数器的 Markdown"""
    total_count = len(cache_data)
    
    # 动态聚合分类：基础分类排前面，新创建的分类紧跟其后
    all_categories = list(DEFAULT_CATEGORIES)
    for item in cache_data.values():
        cat = item.get("category")
        if cat and cat not in all_categories:
            all_categories.append(cat)
            
    content = "# 收藏仓库清单\n\n"
    content += f"> 自动同步于 GitHub Actions · 共收录 **{total_count}** 个项目\n\n"

    # 1. 顶部紧凑导航（TOC）
    content += "### 快速导航\n\n"
    toc_links = []
    for cat in all_categories:
        count = sum(1 for item in cache_data.values() if item.get("category") == cat)
        if count > 0:
            slug = cat.lower().replace(" ", "-").replace("/", "")
            toc_links.append(f"[{cat} ({count})](#{slug})")
    
    content += " · ".join(toc_links) + "\n\n---\n\n"

    # 2. 正文分类列表
    for cat in all_categories:
        matched = [item for item in cache_data.values() if item.get("category") == cat]
        if not matched:
            continue
            
        content += f"## {cat}\n\n"
        for item in matched:
            content += f"- [**{item['name']}**]({item['html_url']}) — {item['summary']}\n"
        content += "\n"

    # 3. 底部装饰：芙莉莲小人 + 萌萌计数器（居中排版）
    content += "---\n\n"
    content += "<p align=\"center\">\n"
    content += "  <img src=\"https://raw.githubusercontent.com/mario-chavez/frieren/main/assets/frieren-walking.gif\" width=\"65\" alt=\"Frieren Walking\" /><br/>\n"
    content += "  <img src=\"https://count.getloli.com/get/@WeiErLiTeo-stars-notes?theme=rule34\" alt=\"Moe Counter\" />\n"
    content += "</p>\n"

    return content

def main():
    if not GEMINI_API_KEY:
        raise ValueError("缺少 GEMINI_API_KEY 环境变量，请在 Settings -> Secrets 中配置。")

    # 1. 加载本地缓存
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    # 2. 拉取线上实时 Star 仓库
    print("正在拉取最新 Starred 列表...")
    starred_list = fetch_all_starred()
    remote_dict = {repo["full_name"]: repo for repo in starred_list}

    # 3. 双向同步：剔除已取消 Star 的项目
    deleted_count = 0
    for cached_name in list(cache.keys()):
        if cached_name not in remote_dict:
            print(f"🗑️ 检测到已取消 Star: {cached_name}，正在清理...")
            del cache[cached_name]
            deleted_count += 1

    # 4. 增量分析：只对新项目调用 Gemini
    new_repos = [repo for full_name, repo in remote_dict.items() if full_name not in cache]
    if new_repos:
        print(f"🔍 发现 {len(new_repos)} 个新增项目需要分析...")
        new_repos.reverse()
        for idx, repo in enumerate(new_repos):
            full_name = repo["full_name"]
            print(f"[{idx+1}/{len(new_repos)}] 处理中: {full_name}")
            desc = repo.get("description", "")
            cat, summary = summarize_with_tiered_chain(full_name, desc)
            
            cache[full_name] = {
                "name": repo["name"],
                "full_name": full_name,
                "html_url": repo["html_url"],
                "category": cat,
                "summary": summary
            }
            time.sleep(3)
    else:
        print("⚡ 没有新增 Star 项目，0 Token 消耗。")

    # 5. 生成精简高密度的 README 并保存
    new_readme = render_compact_readme(cache)
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(new_readme)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"🎉 同步完成！新增: {len(new_repos)}，移除: {deleted_count}，当前总计: {len(cache)}")

if __name__ == "__main__":
    main()
