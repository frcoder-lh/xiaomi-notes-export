""" 小米笔记导出 → Obsidian 从 i.mi.com 获取所有笔记并保存为 Markdown
特性：
  1. 使用 entry.content 完整正文 + 正确的小米笔记 XML→Markdown 转换
  2. 标题取自 extraInfo.title（真实标题），回退到 subject / 正文首行 / 创建时间
  3. 图片附件全部下载到 assets/（同时处理 <img fileid> 新格式与 ☺ fileid 旧格式）
  4. 按文件夹（folderId）把笔记归入子目录
依赖: pip install playwright && playwright install chromium
用法: python export.py [--output OUTPUT_DIR] [--browser edge|chrome]
"""
import os
import re
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

def log(msg):
    print(msg, flush=True)

def safe_filename(name, max_len=80):
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', str(name))
    name = re.sub(r'_+', '_', name)
    name = name.strip('. _')
    if len(name) > max_len:
        name = name[:max_len]
    return name or "无标题"

def format_timestamp(ts):
    if not ts:
        return ""
    try:
        if isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except:
        pass
    return str(ts)

def parse_extra_info(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except:
        return {}

# ─── 小米笔记 XML → Markdown ────────────────────────────────
HEADING_TAGS = [("size", "#"), ("mid-size", "##"), ("h3-size", "###")]
LIST_TYPES = ["checkbox", "bullet", "order"]

def get_indent_level(indent_str):
    try:
        n = int(indent_str or 0)
    except:
        n = 0
    return max(0, n - 1)

def convert_inline_styles(text):
    if not text:
        return ""
    text = re.sub(r'<b>([\s\S]*?)</b>', r'**\1**', text)
    text = re.sub(r'<i>([\s\S]*?)</i>', r'*\1*', text)
    text = re.sub(r'<delete>([\s\S]*?)</delete>', r'~~\1~~', text)
    text = re.sub(r'<u>([\s\S]*?)</u>', r'<u>\1</u>', text)
    def bg(m):
        color, inner = m.group(1), m.group(2)
        return f'<mark style="background:{bgr_to_rgb(color)}">{inner}</mark>'
    text = re.sub(r'<background\s+color="([^"]+)">([\s\S]*?)</background>', bg, text)
    for tag, _ in HEADING_TAGS:
        text = re.sub(rf'<{tag}>([\s\S]*?)</{tag}>', r'**\1**', text)
    return text

def bgr_to_rgb(color):
    if not color or len(color) < 6:
        return color
    hexs = color.replace("#", "")
    return f"#{hexs[4:6]}{hexs[2:4]}{hexs[0:2]}"

def try_parse_heading(content):
    trimmed = content.strip()
    for tag, prefix in HEADING_TAGS:
        m = re.match(rf'^<{tag}>([\s\S]*?)</{tag}>$', trimmed)
        if m:
            return ("heading", f"{prefix} {convert_inline_styles(m.group(1).strip())}")
    return None

def parse_line(line):
    if not line:
        return ("blank", "")
    if re.match(r'^<hr\s*\ ?/>$', line):
        return ("hr", "---")
    m = re.match(r'^<input\s+([^>]*?)type="checkbox"([^>]*?)\s*\ />(.*)$', line)
    if m:
        attrs = m.group(1) + m.group(2)
        im = re.search(r'indent="(\d+)"', attrs)
        cm = re.search(r'checked="(true|false)"', attrs)
        indent = get_indent_level(im.group(1) if im else None)
        checked = cm and cm.group(1) == "true"
        text = convert_inline_styles((m.group(3) or "").strip())
        return ("checkbox", f"{'  '*indent}- [{'x' if checked else ' '}] {text}")
    m = re.match(r'^<order(?:\s+indent="(\d+)")?\s*>([\s\S]*?)</order>$', line)
    if m:
        return ("order", f"{'  '*get_indent_level(m.group(1))}1. {convert_inline_styles(m.group(2).strip())}")
    m = re.match(r'^<bullet(?:\s+indent="(\d+)")?\s*>([\s\S]*?)</bullet>$', line)
    if m:
        return ("bullet", f"{'  '*get_indent_level(m.group(1))}- {convert_inline_styles(m.group(2).strip())}")
    m = re.match(r'^<quote>([\s\S]*?)</quote>$', line)
    if m:
        return ("quote", f"> {convert_inline_styles(m.group(1).strip())}")
    m = re.match(r'^<text(?:\s+indent="(\d+)")?\s*>([\s\S]*?)</text>$', line)
    if m:
        inner = m.group(2)
        if not inner.strip():
            return ("blank", "")
        h = try_parse_heading(inner)
        if h:
            return h
        return ("text", convert_inline_styles(inner.strip()))
    m = re.match(r'^<align\s+align="(center|left|right)">([\s\S]*?)</align>$', line)
    if m:
        return ("text", f'<div align="{m.group(1)}">{convert_inline_styles(m.group(2).strip())}</div>')
    cleaned = convert_inline_styles(line)
    cleaned = re.sub(r'<[^>]+>', '', cleaned).strip()
    return ("text", cleaned) if cleaned else ("blank", "")

def needs_blank_line(prev_type, curr_type):
    if not prev_type:
        return False
    if prev_type == curr_type and curr_type in LIST_TYPES:
        return False
    if prev_type == "text" and curr_type == "text":
        return True
    block_types = ["heading", "hr", "quote"]
    if curr_type in block_types or prev_type in block_types:
        return True
    if (prev_type in LIST_TYPES) != (curr_type in LIST_TYPES):
        return True
    return False

def content_to_markdown(content):
    if not content:
        return ""
    md_lines = []
    prev_type = ""
    for raw in content.split("\n"):
        line = raw.strip()
        if not line:
            continue
        parsed = parse_line(line)
        if parsed is None or parsed[0] == "blank":
            continue
        ptype, ptext = parsed
        if md_lines and needs_blank_line(prev_type, ptype):
            md_lines.append("")
        md_lines.append(ptext)
        prev_type = ptype
    result = "\n".join(md_lines)
    return re.sub(r'\n{3,}', '\n\n', result).strip()

def content_first_line(content):
    """正文首行非空文本（用于标题回退）"""
    for raw in content.split("\n"):
        line = raw.strip()
        if not line:
            continue
        for tag, _ in HEADING_TAGS:
            m = re.match(rf'^<{tag}>([\s\S]*?)</{tag}>$', line)
            if m and m.group(1).strip():
                return re.sub(r'<[^>]+>', '', m.group(1)).strip()[:60]
        t = re.sub(r'<[^>]+>', '', line).strip()
        if re.match(r'^!\[[^\]]*\]\([^)]*\)$', t) or re.match(r'^\[[^\]]*\]\([^)]*\)$', t):
            continue
        t = re.sub(r'^#{1,6}\s*', '', t)
        t = re.sub(r'^[-*]\s+', '', t)
        if t:
            return t[:60]
    return ""

# ─── 附件处理 ───────────────────────────────────────────────
MIME_EXT = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp", "image/heic": ".heic",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/ogg": ".ogg",
    "audio/wav": ".wav", "audio/aac": ".aac", "audio/m4a": ".m4a",
    "video/mp4": ".mp4", "video/quicktime": ".mov",
}
MEDIA_TYPE_PARAM = {"image": "note_img", "audio": "note_audio", "video": "note_video"}

def media_kind(mime):
    return (mime or "").split("/")[0] if (mime or "").split("/")[0] in ("image", "audio", "video") else None

def make_asset_name(file_id, mime):
    dot = file_id.rfind(".")
    idpart = file_id[dot + 1:] if dot >= 0 else file_id
    ext = MIME_EXT.get((mime or "").lower())
    if not ext:
        ext = ".jpg" if (mime or "").startswith("image") else ".bin"
    return f"{idpart}{ext}"

class AssetDownloader:
    """负责按 fileId 全局去重下载附件到 output/assets"""
    def __init__(self, page, assets_abs):
        self.page = page
        self.assets_abs = assets_abs
        self.cache = {}   # fileId -> (name, success)
        self.downloaded = 0
        self.failed = 0

    def ensure(self, file_id, mime):
        if file_id in self.cache:
            return self.cache[file_id]
        kind = media_kind(mime) or "image"
        type_param = MEDIA_TYPE_PARAM.get(kind, "note_img")
        name = make_asset_name(file_id, mime)
        ts = int(time.time() * 1000)
        url = f"https://i.mi.com/file/full?type={type_param}&fileid={file_id}&ts={ts}"
        try:
            r = self.page.request.get(url)
            if r.status != 200:
                log(f"   ⚠️ 附件下载失败 status={r.status}: {file_id}")
                self.cache[file_id] = (None, False)
                self.failed += 1
                return (None, False)
            body = r.body()
            ct = r.headers.get("content-type") or mime
            # 用响应类型修正扩展名
            new_name = make_asset_name(file_id, ct or mime)
            path = self.assets_abs / new_name
            if not path.exists():
                path.write_bytes(body)
            self.cache[file_id] = (new_name, True)
            self.downloaded += 1
            return (new_name, True)
        except Exception as e:
            log(f"   ⚠️ 附件下载异常 {file_id}: {e}")
            self.cache[file_id] = (None, False)
            self.failed += 1
            return (None, False)

def extract_media_refs(content):
    """找出正文中所有媒体引用（新格式 <img fileid> 与旧格式 ☺ fileid），返回 (start, end, fileid) 按位置降序"""
    refs = []
    # 新格式 <img ... fileid="X" .../>
    for m in re.finditer(r'<img\s+[^>]*fileid="([^"]+)"[^>]*\s*\ ?/>', content):
        refs.append((m.start(), m.end(), m.group(1)))
    # 旧格式 ☺ FULLID  （可能带尾部 <...>< /> 标记）
    for m in re.finditer(r'☺\s*([A-Za-z0-9_.-]+)', content):
        refs.append((m.start(), m.end(), m.group(1)))
    # 去重（按位置）
    return sorted(set(refs), key=lambda x: -x[0])

def process_content_media(content, downloader, rel_prefix):
    """把正文中的媒体引用替换为本地 Markdown 引用（从后往前），返回替换后的 content 与引用数"""
    refs = extract_media_refs(content)
    count = 0
    for start, end, fid in refs:
        name, ok = downloader.ensure(fid, None)
        if not ok:
            continue
        rel = f"{rel_prefix}assets/{name}"
        count += 1
        content = content[:start] + f"![{name}]({rel})" + content[end:]
    return content, count

# ─── 浏览器启动 ─────────────────────────────────────────────
def launch_browser(playwright, browser_type="edge"):
    if browser_type == "edge":
        default_profile = os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\User Data")
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "edge-profile")
        channel = "msedge"
    else:
        default_profile = os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data")
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome-profile")
        channel = "chrome"
    if not os.path.exists(profile_dir):
        if not os.path.exists(default_profile):
            raise FileNotFoundError(f"未找到 {browser_type} 用户数据目录: {default_profile}")
        log("⏳ 复制浏览器 profile 到非默认目录（保留登录态）...")
        os.system(f'robocopy "{default_profile}" "{profile_dir}" /E /NFL /NDL /NJH /NJS /NP >nul 2>&1')
        time.sleep(1)
    ctx = playwright.chromium.launch_persistent_context(
        profile_dir, headless=False, channel=channel,
        args=["--disable-blink-features=AutomationControlled"],
        viewport={"width": 1200, "height": 800}, ignore_default_args=["--enable-automation"])
    return ctx

def wait_for_login(page, timeout=300):
    if "account" in page.url or "login" in page.url.lower():
        log("⚠️ 请在弹出的浏览器窗口中登录小米账号...")
        log(" 登录后会自动继续...")
        try:
            page.wait_for_url("**/note/**", timeout=timeout * 1000)
        except:
            pass
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(3000)
        log("✅ 登录成功")

# ─── API ────────────────────────────────────────────────────
def api_fetch(page, url):
    return page.evaluate("""(url) => {
  return fetch(url, { credentials:'include', headers:{'Accept':'application/json'} })
    .then(r=>r.json()).catch(e=>({error:e.message}));
  }""", url)

def fetch_all(page):
    """获取所有笔记 + 文件夹"""
    data = api_fetch(page, "https://i.mi.com/note/full?pageNo=1&pageSize=200")
    entries = list(data.get("data", {}).get("entries", []))
    folders = list(data.get("data", {}).get("folders", []))
    sync_tag = data.get("data", {}).get("syncTag", "")
    seen = set(); all_e = []
    for e in entries:
        if e["id"] not in seen:
            seen.add(e["id"]); all_e.append(e)
    while sync_tag:
        data = api_fetch(page, f"https://i.mi.com/note/full?syncTag={sync_tag}&pageSize=200")
        es = data.get("data", {}).get("entries", [])
        fs = data.get("data", {}).get("folders", [])
        folders.extend(fs)
        new_tag = data.get("data", {}).get("syncTag", "")
        added = 0
        for e in es:
            if e["id"] not in seen:
                seen.add(e["id"]); all_e.append(e); added += 1
        if new_tag == sync_tag:
            break
        sync_tag = new_tag
        if not added:
            break
    return all_e, folders

def fetch_detail(page, note_id):
    data = api_fetch(page, f"https://i.mi.com/note/note/{note_id}")
    if data and isinstance(data.get("data"), dict):
        return data["data"].get("entry") or {}
    return {}

# ─── 主流程 ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="小米笔记导出到 Obsidian")
    parser.add_argument("--output", "-o", default=r"D:\xiaomi", help="输出目录 (默认: D:\\xiaomi)")
    parser.add_argument("--browser", "-b", default="edge", choices=["edge", "chrome"], help="浏览器")
    args = parser.parse_args()

    output_dir = Path(args.output)
    assets_dir = output_dir / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    log("🚀 小米笔记导出工具（完整正文 + 全部图片 + 文件夹）")
    log(f"📁 输出目录: {output_dir}")
    log(f"🌐 浏览器: {args.browser}")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        log("\n🌐 启动浏览器...")
        ctx = launch_browser(p, args.browser)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log("🔗 打开小米笔记...")
        page.goto("https://i.mi.com/note/h5#/", wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        wait_for_login(page)
        log(f"📍 当前页面: {page.url}")

        entries, folders = fetch_all(page)
        folder_map = {str(f.get("id")): f.get("subject") or "" for f in folders}
        if not entries:
            log("❌ 未获取到笔记")
            ctx.close()
            return

        log(f"\n📊 共 {len(entries)} 条笔记，{len(folder_map)} 个文件夹")
        downloader = AssetDownloader(page, assets_dir)

        saved = 0
        notes_data = []
        for i, entry in enumerate(entries):
            eid = entry.get("id")
            detail = fetch_detail(page, eid) if eid else {}
            content = detail.get("content") or entry.get("snippet") or ""
            created = detail.get("createDate") or entry.get("createDate") or 0
            modified = detail.get("modifyDate") or entry.get("modifyDate") or 0
            extra = parse_extra_info(detail.get("extraInfo") or entry.get("extraInfo"))

            # 标题：extraInfo.title → subject → 正文首行 → 创建时间
            title = (extra.get("title") or "").strip()
            if not title:
                title = (entry.get("subject") or "").strip()
            if not title:
                title = content_first_line(content)
            if not title:
                title = format_timestamp(created) or f"笔记{i+1}"
            title = safe_filename(title)

            # 图片：先替换正文引用并下载，再转 Markdown
            folder_id = str(entry.get("folderId") or 0)
            folder_name = folder_map.get(folder_id, "")
            folder_names = [folder_name] if (folder_id != "0" and folder_name) else []
            rel_prefix = "../" * len(folder_names)
            content, img_count = process_content_media(content, downloader, rel_prefix)

            markdown = content_to_markdown(content)
            if not markdown:
                markdown = entry.get("snippet") or ""

            # 输出目录（按文件夹归入子目录）
            note_dir = output_dir
            if folder_names:
                note_dir = output_dir / safe_filename(folder_names[0])
                note_dir.mkdir(parents=True, exist_ok=True)

            fm_txt = "---\n" + f'title: "{title}"\n'
            c = format_timestamp(created); m = format_timestamp(modified)
            if c: fm_txt += f"created: {c}\n"
            if m: fm_txt += f"modified: {m}\n"
            fm_txt += "source: 小米笔记\n---\n\n"
            body = fm_txt + f"# {title}\n\n{markdown}"

            filename = title + ".md"
            filepath = note_dir / filename
            counter = 1
            while filepath.exists():
                filepath = note_dir / f"{title}_{counter}.md"
                counter += 1
            filepath.write_text(body, encoding="utf-8")

            notes_data.append({"title": title, "folder": folder_name, "markdown": markdown,
                               "created": c, "modified": m, "images": img_count})
            saved += 1
            if (i + 1) % 50 == 0 or (i + 1) == len(entries):
                log(f" 📖 {i+1}/{len(entries)}")

        backup_path = output_dir / "_backup.json"
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump(notes_data, f, ensure_ascii=False, indent=2)

        log(f"\n{'='*50}")
        log(f"🎉 导出完成！")
        log(f" 📝 总计: {saved} 条笔记")
        log(f" 📁 文件夹: {len(folder_map)} 个")
        log(f" 🖼️ 下载附件: {downloader.downloaded} 个（失败 {downloader.failed}）")
        log(f" 📁 保存位置: {output_dir}")
        log(f" 💾 JSON 备份: {backup_path}")
        ctx.close()

if __name__ == "__main__":
    main()
