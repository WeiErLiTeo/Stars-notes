import os
import requests
import json
import re
import time

# ================= 配置区域 =================
GITHUB_USERNAME = "WeiErLiTeo"  # 你的 GitHub 账户名
CACHE_FILE = "stars_cache.json"
README_FILE = "README.md"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GH_TOKEN = os.environ.get("GITHUB_TOKEN")

# 完全对齐你当前手机 Lists 中的 13 个真实分类
CATEGORIES = [
    "电脑实用神器",
    "第三方 App",
    "iOS 插件",
    "前端 UI 与动效",
    "数据导出与搬家",
    "实况照片",
    "XP 模块",
    "AI Agent 与工具",
    "福利与自动签到",
    "壁纸与媒体提取",
    "网络与代理",
    "AI Skills",
    "浏览器扩展"
]

HEADERS = {"Accept": "application/vnd.github.v3+json"}
if GH_TOKEN:
    HEADERS["Authorization"] = f"token {GH_TOKEN}"

def fetch_all_starred():
    """全量分页拉取你当前 Starred 的全部仓库（防止超过30个被截断）"""
    starred = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/starred?page={page}&per_page=100"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"获取 Starred 仓库失败: {resp.status_code} - {resp.text}")
            break
        data = resp.json()
        if not data:
            break
        starred.extend(data)
        if len(data) < 100:
            break
        page += 1
    return starred

def summarize_repo(full_name, desc):
    """请求 Gemini 1.5 Flash 提取大白话并严格从 13 个分类中挑选归属"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    categories_str = ", ".join(CATEGORIES)
    prompt = f"""你是一个通俗软件归类助手。请根据仓库信息完成分类和总结。

仓库名称: {full_name}
官方描述: {desc or '无'}

【分类规则】
必须且只能从以下分类池中严格选择一个，绝不能自造分类：
[{categories_str}]

【总结规则】
用一句话（15到25个字以内）讲清楚核心用途。必须用通俗大白话，不带开发黑话（不要出现Hook、SDK、框架等生僻词），让普通人一眼看懂用途。

请直接以严格 JSON 格式输出，不要包含任何多余文字或markdown代码块：
{{"category": "必须在列表里的分类名", "summary": "通俗大白话一句话说明"}}
"""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=20)
        res_data = resp.json()
        raw_text = res_data['candidates'][0]['content']['parts'][0]['text']
        clean_json = re.sub(r'```json|```', '', raw_text).strip()
        data = json.loads(clean_json)
        cat = data.get("category", "").strip()
        if cat not in CATEGORIES:
            cat = "电脑实用神器"
        summary = data.get("summary", "").strip() or (desc[:30] if desc else "暂无说明")
        return cat, summary
    except Exception as e:
        print(f"Gemini 处理 {full_name} 失败: {e}")
        return "电脑实用神器", (desc[:30] if desc else "暂无说明")

def render_readme(cache_data):
    """根据最新缓存，重新格式化生成严格分段、带链接的 README.md"""
    content = "# 🌟 我的 GitHub 收藏大白话备忘录\n\n"
    content += "> 本目录由 GitHub Actions + Gemini 自动实时同步与整理，支持增量收录与取消收藏自动清理。\n\n"
    
    # 按照设定的分类顺序写入
    for cat in CATEGORIES:
        matched = [item for item in cache_data.values() if item.get("category") == cat]
        content += f"## {cat}\n\n"
        if matched:
            for item in matched:
                content += f"* [{item['name']}]({item['html_url']}) — {item['summary']}\n\n"
        else:
            content += "*暂无项目*\n\n"
        content += "---\n\n"
    return content

def main():
    # 1. 加载本地缓存
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    # 2. 拉取线上最新的全部 Star 仓库
    print("正在拉取最新 Star 列表...")
    starred_list = fetch_all_starred()
    remote_full_names = {repo["full_name"]: repo for repo in starred_list}

    # 3. 双向比对：清理已被取消收藏的仓库（Unstarred）
    deleted_count = 0
    for cached_name in list(cache.keys()):
        if cached_name not in remote_full_names:
            print(f"检测到已取消收藏: {cached_name}，正在从缓存移除...")
            del cache[cached_name]
            deleted_count += 1

    # 4. 增量分析：只对未缓存过的新项目调用 Gemini
    new_repos = [repo for full_name, repo in remote_full_names.items() if full_name not in cache]
    
    if new_repos:
        print(f"发现 {len(new_repos)} 个新增项目需要分析...")
        # 逆序处理，保证先收藏的排在合适位置
        new_repos.reverse()
        for idx, repo in enumerate(new_repos):
            full_name = repo["full_name"]
            print(f"[{idx+1}/{len(new_repos)}] 正在分析: {full_name}")
            desc = repo.get("description", "")
            cat, summary = summarize_repo(full_name, desc)
            
            cache[full_name] = {
                "name": repo["name"],
                "full_name": full_name,
                "html_url": repo["html_url"],
                "category": cat,
                "summary": summary
            }
            # 严格控制速率，避免超过 Gemini 免费版的 15 RPM 限制
            time.sleep(4)
    else:
        print("没有发现新的 Star 项目。")

    # 5. 重新生成并覆盖保存 README.md 和 Cache
    new_readme = render_readme(cache)
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(new_readme)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"同步完成！新增: {len(new_repos)}，移除: {deleted_count}，当前总计: {len(cache)}")

if __name__ == "__main__":
    main()
