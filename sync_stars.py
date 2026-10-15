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

# 严格限定 3.0+ 家族：主力 Flash 优先，Lite 严格排在最后垫底
MODELS_CHAIN = [
    "gemini-3.8-flash",       # 1. 旗舰主力 Flash
    "gemini-3.6-flash",       # 2. 备用高配 Flash
    "gemini-3.5-flash",       # 3. 经典通用 Flash
    "gemini-3.1-flash-lite",  # 4. 轻量过渡 Lite
    "gemini-3.5-flash-lite"   # 5. 终极兜底 Lite（高并发底线）
]

# 严格对齐你在手机上建好的 13 个列表分类
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
    """全量分页拉取当前所有已 Star 仓库"""
    starred = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/starred?page={page}&per_page=100"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"拉取 Starred 列表异常: HTTP {resp.status_code}")
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
    categories_str = ", ".join(CATEGORIES)
    return f"""你是一个通俗软件归类助手。请根据仓库信息完成分类和总结。

仓库名称: {full_name}
官方描述: {desc or '无'}

【分类规则】
必须且只能从以下分类池中严格挑选一个最匹配的：
[{categories_str}]

【总结规则】
用一句话（15到25个汉字以内）讲清楚核心用途。必须用通俗大白话，绝不能带技术开发黑话（不要出现 Hook、SDK、框架、MCP 等生僻词），让普通人一眼看懂用途。

请直接以严格 JSON 格式输出：
{{"category": "必须在列表里的分类名", "summary": "通俗大白话一句话说明"}}
"""

def request_gemini_api(model_name, prompt):
    """底层请求单次模型"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    
    gen_config = {
        "temperature": 0.2,
        "responseMimeType": "application/json"
    }
    # 针对带思考机制的 Flash 模型降低推理深度，防止白白消耗多余时间与 token
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
    else:
        raise RuntimeError(f"HTTP {resp.status_code} - {resp.text}")

def summarize_with_tiered_chain(full_name, desc):
    """五级降级轮询机制：依次尝试，直到成功"""
    prompt = build_prompt(full_name, desc)

    for idx, model in enumerate(MODELS_CHAIN):
        try:
            data = request_gemini_api(model, prompt)
            cat = data.get("category", "").strip()
            if cat not in CATEGORIES:
                cat = "电脑实用神器"
            summary = data.get("summary", "").strip() or (desc[:30] if desc else "暂无说明")
            
            if idx > 0:
                print(f"✅ 备选模型 [{model}] 成功接管处理！")
            return cat, summary
        except Exception as e:
            print(f"⚠️ [{model}] 请求失败: {e}")
            if idx < len(MODELS_CHAIN) - 1:
                next_model = MODELS_CHAIN[idx + 1]
                print(f"🔄 自动切入下一顺位: [{next_model}]...")
                time.sleep(1)

    print("❌ 3.0+ 家族所有梯队模型均调用失败，执行本地兜底。")
    return "电脑实用神器", (desc[:30] if desc else "暂无说明")

def render_readme(cache_data):
    """根据最新数据重绘 Markdown 目录"""
    content = "# 🌟 我的 GitHub 收藏大白话备忘录\n\n"
    content += "> 由 GitHub Actions + Gemini 3.0+ 全模型梯队自动维护，支持新增分类与取消收藏自动清理。\n\n"
    
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
    if not GEMINI_API_KEY:
        raise ValueError("未检测到环境变量 GEMINI_API_KEY，请在仓库 Settings -> Secrets 中设置。")

    # 1. 读取本地缓存
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
            print(f"🗑️ 检测到已取消 Star: {cached_name}，正在自动清理...")
            del cache[cached_name]
            deleted_count += 1

    # 4. 增量分析：只对新项目调用梯队模型
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
            # 安全延时，避免触发全局频率限制
            time.sleep(3)
    else:
        print("⚡ 没有新增 Star 项目，本次执行未消耗任何 Token。")

    # 5. 生成并覆盖写入
    new_readme = render_readme(cache)
    with open(README_FILE, "w", encoding="utf-8") as f:
        f.write(new_readme)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

    print(f"🎉 同步完成！新增: {len(new_repos)}，移除: {deleted_count}，当前总收录: {len(cache)}")

if __name__ == "__main__":
    main()
