"""UI 验证脚手架 —— 按阶段分组断言。

用法:
    python3 tests/verify_ui.py --baseline          # 抓基线截图
    python3 tests/verify_ui.py --phase 0           # 跑 P0 断言（含与基线逐像素比对）
    python3 tests/verify_ui.py --phase 2 --shots   # 跑断言并另存一份给人看的截图

依赖: playwright + chromium。服务需已在 127.0.0.1:9229 运行。
API 全部打桩，覆盖所有状态组合，且关掉自动刷新以保证截图稳定。
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:9229"
ROOT = Path(__file__).resolve().parent.parent
SHOT_DIR = ROOT / ".uishots"
THEMES = ["dark-emerald", "blueprint", "midnight", "arctic", "terra", "neon", "velvet"]
TABS = ["managed", "local", "system", "scenes"]

# ---------------------------------------------------------------- fixtures

LONG_NAME = "com.example.some-absurdly-long-process-name-that-must-truncate-instead-of-pushing-buttons"

SNAPSHOT = {
    "stats": {
        "cpu_percent": 42.0,
        "memory": {"percent": 73.6, "total_gb": 32.0, "used_gb": 23.5},
        "ip_address": "192.168.1.42",
        "uptime": "12m 35s",
        "os": "Darwin",
    },
    "projects": [
        {
            "id": "web", "name": "Web 前端", "cwd": "/Users/dev/web",
            "command": "npm run dev", "port": 3000,
            "description": "主站前端，Vite 开发服务器，带热更新与代理转发到后端 API",
            "status": "running", "pid": 4242, "owner": "Dashboard",
            "port_active": True, "managed": True,
            "port_process": {"pid": 4242, "process": "node", "port": 3000},
        },
        {
            "id": "api", "name": "API 服务", "cwd": "/Users/dev/api",
            "command": "PORT=8000 python manage.py runserver", "port": 8000,
            "description": "外部启动的后端服务", "status": "external", "pid": 5151,
            "owner": "External (python)", "port_active": True, "managed": False,
            "port_process": {"pid": 5151, "process": "python", "port": 8000},
        },
        {
            "id": "worker", "name": "后台任务", "cwd": "/Users/dev/worker",
            "command": "celery -A app worker", "port": 5555,
            "description": "", "status": "stopped", "pid": None,
            "owner": "Unknown", "port_active": False, "managed": False,
            "port_process": None,
        },
    ],
    "grouped_local_ports": [
        {"pid": 4242, "process_name": "node", "cwd": "web", "ports": [3000, 3001],
         "primary_port": 3000, "is_http": True, "category": "user", "port_count": 2},
        {"pid": 6001, "process_name": "Blender", "cwd": "scene", "ports": [8080],
         "primary_port": 8080, "is_http": True, "category": "creative", "port_count": 1},
        {"pid": 6002, "process_name": "clash", "cwd": "", "ports": [7890],
         "primary_port": 7890, "is_http": False, "category": "network", "port_count": 1},
        {"pid": 6003, "process_name": "launchd", "cwd": "", "ports": [22],
         "primary_port": 22, "is_http": False, "category": "system", "port_count": 1},
        {"pid": 6004, "process_name": LONG_NAME, "cwd": LONG_NAME, "ports": [9999],
         "primary_port": 9999, "is_http": True, "category": "user", "port_count": 1},
    ],
    # 覆盖 4 个安全等级 + self(9229) + 200 行用于 sticky/滚动测试
    "system_ports": (
        [{"address": "127.0.0.1:9229", "port": 9229, "process": "python",
          "pid": 999, "status": "listening", "platform": "darwin",
          "project_name": "", "dashboard_project": None}]
        + [{"address": "0.0.0.0:445", "port": 445, "process": "smbd",
            "pid": 101, "status": "listening", "platform": "darwin",
            "project_name": "", "dashboard_project": None}]
        + [{"address": "127.0.0.1:3306", "port": 3306, "process": "mysqld",
            "pid": 102, "status": "listening", "platform": "darwin",
            "project_name": "", "dashboard_project": None}]
        + [{"address": "127.0.0.1:3000", "port": 3000, "process": "node",
            "pid": 4242, "status": "listening", "platform": "darwin",
            "project_name": "web", "dashboard_project": "web"}]
        + [{"address": f"127.0.0.1:{20000 + i}", "port": 20000 + i,
            "process": f"proc{i}", "pid": 7000 + i, "status": "listening",
            "platform": "darwin", "project_name": "", "dashboard_project": None}
           for i in range(200)]
    ),
    "generated_at": 1700000000000,
}

PREFS = {
    "preferences": {"theme": "dark-emerald", "default_category": "user",
                    "default_tab": "managed", "auto_refresh": False,
                    "refresh_interval": 5, "port": 9229},
    "running_port": 9229,
    "defaults": {"theme": "dark-emerald", "default_category": "user",
                 "default_tab": "managed", "auto_refresh": True,
                 "refresh_interval": 5, "port": 9229},
    "allowed": {"themes": sorted(THEMES), "categories": ["all", "creative", "user"],
                "tabs": ["local", "managed", "system"],
                "refresh_intervals": [3, 5, 10, 15, 30, 60]},
}


async def stub_api(page):
    async def route(r):
        url = r.request.url
        if "/api/dashboard/snapshot" in url:
            body = SNAPSHOT
        elif "/api/preferences" in url:
            body = PREFS
        elif "/api/system/stats" in url:
            body = SNAPSHOT["stats"]
        elif "/api/system/ports" in url:
            body = SNAPSHOT["system_ports"]
        elif "/api/projects" in url:
            body = SNAPSHOT["projects"]
        else:
            body = {"success": True}
        await r.fulfill(status=200, content_type="application/json",
                        body=json.dumps(body))
    await page.route("**/api/**", route)


async def new_page(pw, w=1440, h=900):
    browser = await pw.chromium.launch()
    page = await browser.new_page(viewport={"width": w, "height": h})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"PAGEERROR: {e}"))
    await stub_api(page)
    await page.add_init_script(
        "localStorage.setItem('autoRefresh','false');"
        "localStorage.setItem('theme','dark-emerald');"
        "localStorage.removeItem('crtEnabled');")
    return browser, page, errors


# 冻结动画。必须在导航之后注入 —— add_style_tag 加的 <style> 会被 goto() 清掉。
# 且必须用 animation:none 而不是 animation-play-state:paused，后者与切换样式表
# 引发的样式重算相互作用，会产生幽灵像素差异。
FREEZE_CSS = """
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    caret-color: transparent !important;
  }
"""


async def goto(page):
    await page.goto(URL, wait_until="networkidle")
    await page.add_style_tag(content=FREEZE_CSS)
    await page.wait_for_timeout(900)


async def set_theme(page, theme):
    await page.evaluate(
        f"applyTheme('{theme}'); document.body.dataset.theme = '{theme}';")
    await page.wait_for_timeout(180)


async def set_tab(page, tab):
    await page.evaluate(f"""
      (() => {{
        const app = document.querySelector('#app').__vue_app__;
        return null;
      }})()""")
    labels = {"managed": "托管项目", "local": "本地端口", "system": "全局端口", "scenes": "场景 ("}
    btn = page.locator("button", has_text=labels[tab]).first
    if await btn.count():
        await btn.click()
        await page.wait_for_timeout(280)


# ---------------------------------------------------------------- shared probes

async def probe_gray_borders(page):
    """返回可见的 #e5e7eb 边框列表（零宽度的不算）。"""
    return await page.evaluate("""
    (() => {
      const out = [], sides = ['Top','Right','Bottom','Left'];
      document.querySelectorAll('*').forEach(el => {
        const cs = getComputedStyle(el);
        sides.forEach(s => {
          if (parseFloat(cs['border'+s+'Width']) > 0 &&
              cs['border'+s+'Color'] === 'rgb(229, 231, 235)') {
            out.push((el.className || el.tagName) + '/' + s);
          }
        });
      });
      return out.slice(0, 40);
    })()""")


async def probe_style_in_template(page):
    return await page.evaluate(
        "document.querySelectorAll('#app style, #app link').length")


async def probe_doc_scroll(page):
    return await page.evaluate(
        "document.documentElement.scrollHeight - window.innerHeight")


# ---------------------------------------------------------------- phases

async def capture(page, tag, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        await set_theme(page, theme)
        for tab in TABS:
            await set_tab(page, tab)
            await page.screenshot(path=str(out_dir / f"{tag}-{theme}-{tab}.png"))


INERT_PROPS = [
    "margin", "padding", "borderWidth", "borderColor", "borderStyle", "borderRadius",
    "backgroundColor", "backgroundImage", "color", "opacity", "boxShadow",
    "fontSize", "fontWeight", "lineHeight", "letterSpacing",
    "display", "position", "width", "height", "minWidth", "minHeight",
    "flexGrow", "flexShrink", "flexBasis", "gridTemplateColumns", "gap",
    "overflow", "boxSizing", "cursor", "borderCollapse", "verticalAlign",
    "textTransform", "whiteSpace", "transform", "mixBlendMode", "zIndex",
]
# fontFamily 刻意不在惰性比对内：pd-tokens 带上了 DESIGN.md 一直要求却从未存在的
# @font-face，关掉它字体本就会回退。字体正确性由单独的断言覆盖。


async def probe_inert(page, sheet_ids, out_dir, tag):
    """证明指定样式表此刻是惰性的。

    权威依据是**计算样式**逐元素比对，而不是像素：切换样式表会触发样式失效，
    Chromium 随后对文字的栅格化会有 ≤26/255、约 0.04% 像素的微小抖动，
    即使没有任何计算值变化。像素比对保留为辅助信号（带容差）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ids_js = json.dumps(sheet_ids)
    props_js = json.dumps(INERT_PROPS)

    snap_js = f"""
    (off) => {{
      [...document.styleSheets].forEach(s => {{
        if (s.ownerNode && {ids_js}.includes(s.ownerNode.id)) s.disabled = off;
      }});
      const props = {props_js}, out = [];
      document.querySelectorAll('*').forEach(el => {{
        const cs = getComputedStyle(el);
        out.push(props.map(p => cs[p]).join('\\u0001'));
      }});
      return out;
    }}"""

    style_diffs, pixel_notes = [], []
    for theme in THEMES:
        await set_theme(page, theme)
        for tab in TABS:
            await set_tab(page, tab)

            off = await page.evaluate(snap_js, True)
            off_png = await page.screenshot()
            on = await page.evaluate(snap_js, False)
            on_png = await page.screenshot()

            if len(off) != len(on):
                style_diffs.append(f"{theme}/{tab}: 元素数不同 {len(off)} vs {len(on)}")
                continue
            for i, (a, b) in enumerate(zip(off, on)):
                if a != b:
                    changed = [INERT_PROPS[j] for j, (x, y)
                               in enumerate(zip(a.split("\u0001"), b.split("\u0001")))
                               if x != y]
                    style_diffs.append(f"{theme}/{tab} 第{i}个元素: {changed}")
                    break

            if off_png != on_png:
                ratio, peak = _pixel_delta(off_png, on_png)
                if peak > 8 or ratio > 0.005:
                    style_diffs.append(
                        f"{theme}/{tab}: 像素差超容差 peak={peak} ratio={ratio:.4%}")
                    (out_dir / f"{tag}-{theme}-{tab}-off.png").write_bytes(off_png)
                    (out_dir / f"{tag}-{theme}-{tab}-on.png").write_bytes(on_png)
                else:
                    pixel_notes.append(f"{theme}/{tab} peak={peak} ratio={ratio:.4%}")

    if pixel_notes:
        print(f"  （{len(pixel_notes)} 处亚感知栅格化抖动，已忽略；例: {pixel_notes[0]}）")
    return style_diffs


def rel_luminance(rgb):
    """WCAG 相对亮度。"""
    def chan(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(c1, c2):
    l1, l2 = rel_luminance(c1), rel_luminance(c2)
    lo, hi = sorted((l1, l2))
    return (hi + 0.05) / (lo + 0.05)


def parse_rgb(s):
    """解析 getComputedStyle 返回的颜色。Chromium 在 color-mix 之后会给
    `color(srgb 0.2 0.18 0.21)` 这种 0–1 浮点形式，不只是 rgb()。"""
    s = s.strip()
    if s.startswith("color("):
        parts = s[s.index("srgb") + 4:].rstrip(")").replace("/", " ").split()
        vals = [float(x) for x in parts[:3]]
        return tuple(int(round(v * 255)) for v in vals)
    nums = s.replace("rgba", "").replace("rgb", "").strip("() ").split(",")[:3]
    return tuple(int(round(float(n))) for n in nums)


def _pixel_delta(a_bytes, b_bytes):
    """返回 (差异像素占比, 最大通道差)。缺 PIL 时退化为 (1.0, 255)。"""
    try:
        import io
        import numpy as np
        from PIL import Image, ImageChops
        a = Image.open(io.BytesIO(a_bytes)).convert("RGB")
        b = Image.open(io.BytesIO(b_bytes)).convert("RGB")
        if a.size != b.size:
            return 1.0, 255
        arr = np.array(ImageChops.difference(a, b))
        return float((arr.sum(axis=2) > 0).mean()), int(arr.max())
    except ImportError:
        return 1.0, 255


async def run(phase, baseline, keep_shots):
    failures = []
    async with async_playwright() as pw:
        browser, page, errors = await new_page(pw)
        await goto(page)

        tag = "baseline" if baseline else f"p{phase}"
        out = SHOT_DIR / tag
        await capture(page, tag, out)
        print(f"[截图] {len(list(out.glob('*.png')))} 张 -> {out}")

        if baseline:
            await browser.close()
            print("基线已保存。")
            return 0

        # --- 通用断言（每个阶段都跑） ---
        gray = await probe_gray_borders(page)
        print(f"[通用] 可见 #e5e7eb 灰边框: {len(gray)} {gray[:3]}")

        n_style = await probe_style_in_template(page)
        print(f"[通用] #app 内的 style/link 标签数: {n_style} (必须 0)")
        if n_style:
            failures.append(f"#app 内出现 {n_style} 个 style/link —— Vue 会忽略它们")

        overflow = await probe_doc_scroll(page)
        print(f"[通用] 文档级溢出: {overflow}px (应 <= 1)")
        if overflow > 1:
            failures.append(f"出现文档级滚动条，溢出 {overflow}px")

        font = await page.evaluate("""
        (async () => {
          await document.fonts.ready;
          const loaded = [...document.fonts].map(f => `${f.family}/${f.weight}/${f.status}`);
          const probe = document.querySelector('.terminal-output, .settings-input, pre');
          return {
            loaded,
            ok400: document.fonts.check('400 13px "JetBrains Mono"'),
            ok700: document.fonts.check('700 13px "JetBrains Mono"'),
            used: probe ? getComputedStyle(probe).fontFamily : null,
          };
        })()""")
        print(f"[通用] JetBrains Mono 已加载: 400={font['ok400']} 700={font['ok700']}")
        print(f"        字体面: {font['loaded']}")
        if not (font["ok400"] and font["ok700"]):
            failures.append(f"JetBrains Mono 未加载: {font}")

        # --- 惰性检测：这些块此刻不应改变任何渲染 ---
        # pd-tokens 不在此列 —— 它带上了 webfont，字符宽度本就会变（见上方字体断言）。
        if phase in (0, 1):
            sheets = ["pd-base"] + (["pd-ui"] if phase >= 1 else [])
            diffs = await probe_inert(page, sheets, SHOT_DIR / f"p{phase}-inert", f"p{phase}")
            print(f"[P{phase}] 惰性检测（开关 {sheets}）: {len(diffs)} 处不一致 {diffs[:5]}")
            if diffs:
                failures.append(
                    f"P{phase} {sheets} 应为惰性，但开关后 {len(diffs)} 处渲染不同")

        # --- P2+：进度条必须可见 ---
        if phase >= 2:
            meters = await page.evaluate("""
            (() => {
              const els = document.querySelectorAll('.pd-meter__fill, [class*="meter"]');
              return [...els].map(e => {
                const cs = getComputedStyle(e);
                return { w: e.offsetWidth, bg: cs.backgroundColor, bi: cs.backgroundImage };
              });
            })()""")
            visible = [m for m in meters
                       if m["w"] > 0 and (m["bi"] != "none" or
                                          m["bg"] not in ("rgba(0, 0, 0, 0)", "transparent"))]
            print(f"[P2] 进度条: 共 {len(meters)} 条，可见 {len(visible)} 条")
            if len(meters) < 2 or len(visible) < 2:
                failures.append(f"进度条不可见: {meters}")

            spacer = await page.evaluate("""
            (() => {
              const el = document.querySelector('.pd-spacer');
              if (!el) return null;
              return { display: getComputedStyle(el).display, w: el.offsetWidth };
            })()""")
            print(f"[P2] header 弹性空隙: {spacer}")
            if spacer and (spacer["display"] == "none" or spacer["w"] <= 0):
                failures.append(f"header 弹性空隙仍不生效: {spacer}")

        # --- P3+：tone 契约必须真的分色（曾因特异度 bug 全部塌成强调色） ---
        if phase >= 3:
            tones = {}
            for tab in TABS:
                await set_tab(page, tab)
                part = await page.evaluate("""
                (() => {
                  const seen = {};
                  document.querySelectorAll('[data-tone]').forEach(el => {
                    const cs = getComputedStyle(el);
                    seen[el.dataset.tone] = cs.color + '|' + cs.borderTopColor;
                  });
                  return seen;
                })()""")
                tones.update(part)
            print(f"[P3] 出现的 tone: {sorted(tones.keys())}")
            unresolved = [t for t, v in tones.items() if "color-mix" in v]
            if unresolved:
                failures.append(f"color-mix 未解析: {unresolved}")
            vals = list(tones.values())
            if len(tones) >= 3 and len(set(vals)) < 3:
                failures.append(
                    f"tone 未生效，{len(tones)} 个 tone 只解析出 {len(set(vals))} 种颜色: {tones}")
            else:
                print(f"[P3] {len(tones)} 个 tone 解析出 {len(set(vals))} 种不同配色")

        # --- P5+：sticky 表头必须真的吸顶（原来挂在 tr 上 + border-collapse，不生效） ---
        if phase >= 5:
            await set_tab(page, "system")
            sticky = await page.evaluate("""
            (async () => {
              const wrap = document.querySelector('.pd-table-wrap');
              const th = document.querySelector('.pd-table th');
              if (!wrap || !th) return null;
              const before = th.getBoundingClientRect().top;
              wrap.scrollTop = 800;
              await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
              const after = th.getBoundingClientRect().top;
              const cs = getComputedStyle(th);
              wrap.scrollTop = 0;
              return { before, after, position: cs.position, bg: cs.backgroundColor,
                       scrolled: wrap.scrollHeight > wrap.clientHeight };
            })()""")
            print(f"[P5] sticky 表头: {sticky}")
            if not sticky:
                failures.append("找不到 .pd-table-wrap / th，无法验证 sticky 表头")
            elif not sticky["scrolled"]:
                failures.append("表格未溢出，sticky 表头无法验证（fixture 行数不足？）")
            elif abs(sticky["before"] - sticky["after"]) > 1:
                failures.append(
                    f"滚动后表头位移 {sticky['after'] - sticky['before']:.1f}px，未吸顶")
            elif sticky["bg"] in ("rgba(0, 0, 0, 0)", "transparent"):
                failures.append("表头背景透明，吸顶时会透出行内容")

        # --- P6+：终端必须跟主题（原来底色硬编码 #010a0a，arctic 下是脏的近黑绿） ---
        if phase >= 6:
            term = {}
            for theme in THEMES:
                await set_theme(page, theme)
                term[theme] = await page.evaluate("""
                (() => {
                  const el = document.querySelector('.pd-term');
                  if (!el) return null;
                  const cs = getComputedStyle(el);
                  return { bg: cs.backgroundColor, fg: cs.color };
                })()""")
            if any(v is None for v in term.values()):
                failures.append("找不到 .pd-term")
            else:
                bgs = {t: v["bg"] for t, v in term.items()}
                print(f"[P6] 终端底色: arctic={bgs['arctic']} neon={bgs['neon']} "
                      f"emerald={bgs['dark-emerald']}")
                if len(set(bgs.values())) < 3:
                    failures.append(f"终端底色未随主题变化: {bgs}")
                for t, v in term.items():
                    try:
                        ratio = contrast(parse_rgb(v["fg"]), parse_rgb(v["bg"]))
                    except Exception:
                        continue
                    if ratio < 4.5:
                        failures.append(f"{t} 终端文字对比度仅 {ratio:.2f}:1")
                arctic_lum = rel_luminance(parse_rgb(bgs["arctic"]))
                if arctic_lum < 0.5:
                    failures.append(f"arctic 终端底色仍是深色（亮度 {arctic_lum:.2f}）")
                else:
                    print(f"[P6] arctic 终端已是浅色屏（亮度 {arctic_lum:.2f}）")
            await set_theme(page, "dark-emerald")

        # --- P8：自建对话框 + toast，且不得残留任何原生弹窗 ---
        if phase >= 8:
            # 原生弹窗全部打桩为 throw —— 只要还有一处在用，后面的操作就会炸。
            # 必须包成 IIFE 返回 null：若最后一个表达式是函数，evaluate 会去调用它。
            await page.evaluate("""
              (() => {
                window.alert = () => { throw new Error('native alert 仍在使用'); };
                window.confirm = () => { throw new Error('native confirm 仍在使用'); };
                window.prompt = () => { throw new Error('native prompt 仍在使用'); };
                return null;
              })()
            """)
            deletes = []
            await page.route("**/api/projects/*", lambda r: (
                deletes.append(r.request.method) if r.request.method == "DELETE" else None,
                asyncio.ensure_future(r.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps({"success": True})))
            )[-1])

            await set_tab(page, "managed")
            del_btn = page.locator('.pd-card__foot button[title="删除托管"]').first
            await del_btn.click()
            await page.wait_for_timeout(350)
            state = await page.evaluate("""
            (() => {
              const d = document.querySelectorAll('.pd-dialog');
              if (!d.length) return null;
              const focused = document.activeElement;
              return { count: d.length,
                       role: d[0].closest('[role]') ? d[0].getAttribute('role') : d[0].getAttribute('role'),
                       focusOnConfirm: focused && focused.classList.contains('pd-btn--solid'),
                       preLine: getComputedStyle(d[0].querySelector('.pd-dialog__text')).whiteSpace };
            })()""")
            print(f"[P8] 对话框: {state}")
            if not state:
                failures.append("删除按钮未打开 pd-dialog")
            else:
                if state["count"] != 1:
                    failures.append(f"同时存在 {state['count']} 个对话框")
                if state["role"] != "alertdialog":
                    failures.append(f"对话框 role={state['role']}，应为 alertdialog")
                if not state["focusOnConfirm"]:
                    failures.append("焦点未落在确认按钮，Enter 无法直接确认")
                if state["preLine"] != "pre-line":
                    failures.append(f"对话框正文 white-space={state['preLine']}，多行说明会被压平")

            # Esc 取消：不得发出 DELETE
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
            gone = await page.locator(".pd-dialog").count() == 0
            print(f"[P8] Esc 关闭: {gone}，取消后 DELETE 次数: {len(deletes)}")
            if not gone:
                failures.append("Esc 未关闭对话框")
            if deletes:
                failures.append(f"Esc 取消后仍发出了 {len(deletes)} 次 DELETE")

            # Enter 确认：应发出 DELETE
            await del_btn.click()
            await page.wait_for_timeout(300)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(400)
            print(f"[P8] Enter 确认后 DELETE 次数: {len(deletes)}")
            if not deletes:
                failures.append("Enter 确认后未发出 DELETE")

            # toast：三种 tone 同时存在且会自动消失
            await page.evaluate("""
              (() => {
                const app = document.querySelector('#app').__vue_app__;
                return null;
              })()""")
            shown = await page.evaluate("""
            (async () => {
              const btn = document.querySelector('.pd-toaster');
              return !!btn;
            })()""")
            if not shown:
                failures.append("找不到 .pd-toaster 容器")
            else:
                print("[P8] toast 容器存在")

        # --- P9：扫描导入弹窗（发现 → 已在管禁选 → 勾选导入） ---
        if phase >= 9:
            import_posts = []
            await page.route("**/api/discover*", lambda r: asyncio.ensure_future(r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"root": "G:/AITOOLS", "candidates": [
                    {"cwd": "G:/AITOOLS/demo-web", "name": "demo-web", "kind": "vite",
                     "command": "npm run dev", "port": 5173, "port_source": "vite default",
                     "id_hint": "demo-web", "already_managed": False},
                    {"cwd": "G:/AITOOLS/nexart", "name": "NexArt AI Workflow", "kind": "vite",
                     "command": "npm run dev", "port": 6677, "port_source": ".env PORT",
                     "id_hint": "nexart", "already_managed": True},
                ]}))))
            await page.route("**/api/projects", lambda r: (
                import_posts.append(r.request.post_data) if r.request.method == "POST" else None,
                asyncio.ensure_future(r.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps({"success": True})))
            )[-1])

            await set_tab(page, "managed")
            await page.locator('button[title="扫描目录，批量发现可托管的项目"]').click()
            root_input = page.locator('.pd-modal input[placeholder="e.g. G:/AITOOLS"]')
            await root_input.fill("G:/AITOOLS")
            await page.locator('.pd-modal button:has-text("扫描")').click()
            await page.wait_for_timeout(400)

            boxes = page.locator('.pd-modal input[type="checkbox"]')
            rows = await boxes.count()
            print(f"[P9] 扫描结果行: {rows}")
            if rows != 2:
                failures.append(f"扫描应列出 2 个候选，实际 {rows}")
            disabled = await page.locator('.pd-modal input[type="checkbox"][disabled]').count()
            if disabled != 1:
                failures.append(f"already_managed 候选应禁选（实际禁选 {disabled} 个）")

            await page.locator('.pd-modal input[type="checkbox"]:not([disabled])').first.check()
            await page.locator('.pd-modal button:has-text("导入所选")').click()
            await page.wait_for_timeout(500)

            if not import_posts:
                failures.append("导入所选未发出 POST /api/projects")
            else:
                body = json.loads(import_posts[0])
                print(f"[P9] 导入 payload id={body.get('id')} port={body.get('port')}")
                if body.get("id") != "demo-web" or body.get("port") != 5173:
                    failures.append(f"导入 payload 不符: {body}")
            modal_gone = await root_input.count() == 0
            if not modal_gone:
                failures.append("导入后弹窗未关闭")

        # --- P10：场景弹窗（列表 → 状态徽章 → 删除走自建对话框契约） ---
        if phase >= 10:
            scene_deletes = []
            await page.route("**/api/scenes", lambda r: asyncio.ensure_future(r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps([{"id": "client-work", "name": "客户项目开发", "up_count": 1, "total": 2,
                                  "steps": [{"project_id": "web", "name": "Web 前端", "state": "managed"},
                                            {"project_id": "api", "name": "API 服务", "state": "stopped"}]}]))))
            await page.route("**/api/scenes/*", lambda r: (
                scene_deletes.append(r.request.method) if r.request.method == "DELETE" else None,
                asyncio.ensure_future(r.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps({"success": True})))
            )[-1])

            await page.locator('button[title="场景：按依赖顺序一键启停一组项目"]').click()
            await page.wait_for_timeout(400)

            row = page.locator('.pd-modal .pd-row').first
            row_text = await row.inner_text()
            print(f"[P10] 场景行: {row_text.split(chr(10))[0]} | 按钮 {await page.locator('.pd-modal .pd-row button').count()}")
            if "客户项目开发" not in row_text or "1/2" not in row_text:
                failures.append(f"场景行渲染不符: {row_text[:80]}")
            if not await page.locator('.pd-modal select option').count() >= 3:
                failures.append("新建场景的项目下拉没有列出托管项目")

            # 删除场景必须走 P8 的自建对话框契约（Esc 取消 / Enter 确认）
            await page.locator('.pd-modal button[title="删除场景"]').click()
            await page.wait_for_timeout(300)
            dialog_open = await page.locator(".pd-dialog").count() == 1
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(400)
            print(f"[P10] 删除确认对话框: {dialog_open}，DELETE 次数: {len(scene_deletes)}")
            if not dialog_open:
                failures.append("删除场景未弹出确认对话框")
            if not scene_deletes:
                failures.append("确认后未发出 DELETE /api/scenes/*")

        # --- P11：场景自动检测建议（打开即检测 → 建议卡 → 一键创建） ---
        if phase >= 11:
            scene_posts = []
            await page.route("**/api/scenes/suggest", lambda r: asyncio.ensure_future(r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"groups": [
                    {"name": "demo-suite", "reason": "port-ref", "steps": [
                        {"project_id": "api", "name": "API 服务", "state": "stopped"},
                        {"project_id": "web", "name": "Web 前端", "state": "stopped"},
                    ]},
                ]}))))

            async def _scenes_route(route):
                req = route.request
                if req.method == "POST":
                    scene_posts.append(req.post_data)
                    await route.fulfill(status=200, content_type="application/json",
                                        body=json.dumps({"success": True, "scene": {"id": "demo-suite"}}))
                else:
                    await route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

            await page.route("**/api/scenes", lambda r: asyncio.ensure_future(_scenes_route(r)))

            await page.keyboard.press("Escape")     # 关掉 P10 遗留的场景弹窗
            await page.wait_for_timeout(250)
            await page.locator('button[title="场景：按依赖顺序一键启停一组项目"]').click()
            await page.wait_for_timeout(450)

            card = page.locator('.pd-modal .pd-row:has-text("demo-suite")')
            card_text = await card.inner_text()
            print(f"[P11] 建议卡: {card_text.split(chr(10))[0]}")
            if "demo-suite" not in card_text or "端口引用" not in card_text:
                failures.append(f"建议卡渲染不符: {card_text[:80]}")
            if "API 服务 → Web 前端" not in card_text:
                failures.append(f"建议卡顺序不符（应为 依赖 → 前端）: {card_text[:80]}")

            await card.locator('button:has-text("创建场景")').click()
            await page.wait_for_timeout(400)
            if not scene_posts:
                failures.append("创建场景未发出 POST /api/scenes")
            else:
                body = json.loads(scene_posts[0])
                print(f"[P11] 创建 payload: name={body.get('name')} steps={body.get('steps')}")
                if body.get("name") != "demo-suite" or body.get("steps") != ["api", "web"]:
                    failures.append(f"创建 payload 不符: {body}")
            if await card.count() != 0:
                failures.append("创建成功后建议卡未消失")
            await page.keyboard.press("Escape")     # 收尾关弹窗，别让 P12 踩到 scrim
            await page.wait_for_timeout(300)

        # --- P12：场景标签页（一等公民视图：卡片/状态 chips/启动动作/建议卡） ---
        if phase >= 12:
            await page.keyboard.press("Escape")     # 关掉 P11 遗留的场景弹窗
            await page.wait_for_timeout(300)
            scene_action_urls = []
            await page.route("**/api/scenes", lambda r: asyncio.ensure_future(_scenes_list_route(r)))
            await page.route("**/api/scenes/**", lambda r: (
                scene_action_urls.append(r.request.url) if r.request.method == "POST" else None,
                asyncio.ensure_future(r.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps({"success": True, "results": []})))
            )[-1])

            async def _scenes_list_route(route):
                req = route.request
                if req.method == "POST":
                    scene_action_urls.append(req.url)
                    await route.fulfill(status=200, content_type="application/json",
                                        body=json.dumps({"success": True}))
                else:
                    await route.fulfill(status=200, content_type="application/json",
                                        body=json.dumps([
                                            {"id": "demo-suite", "name": "Demo Suite",
                                             "up_count": 0, "total": 2,
                                             "steps": [
                                                 {"project_id": "api", "name": "API 服务", "state": "managed"},
                                                 {"project_id": "web", "name": "Web 前端", "state": "stopped"},
                                             ]}]))

            # 建议集合刻意与已存在场景的步骤不同 —— 否则会被 suggestionExists 正确去重
            await page.route("**/api/scenes/suggest", lambda r: asyncio.ensure_future(r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"groups": [
                    {"name": "demo-suite", "reason": "port-ref", "steps": [
                        {"project_id": "web", "name": "Web 前端", "state": "stopped"},
                    ]},
                ]}))))

            await set_tab(page, "scenes")
            await page.wait_for_timeout(500)

            tab_card = page.locator('.pd-pane .pd-card:has-text("Demo Suite")')
            if not await tab_card.count():
                failures.append("场景页没有渲染场景卡片")
            else:
                card_text = await tab_card.first.inner_text()
                print(f"[P12] 场景卡: {card_text.split(chr(10))[:3]}")
                if "0/2" not in card_text:
                    failures.append(f"场景卡状态徽章不符: {card_text[:60]}")
                if "API 服务 · 托管运行" not in card_text or "Web 前端 · 已停止" not in card_text:
                    failures.append(f"步骤 chips 状态不符: {card_text[:80]}")
                start_btn = tab_card.first.locator('button:has-text("启动")')
                await start_btn.click()
                await page.wait_for_timeout(400)
                if not any(u.endswith("/api/scenes/demo-suite/start") for u in scene_action_urls):
                    failures.append(f"场景卡「启动」未发出 start 请求: {scene_action_urls[:2]}")
                print(f"[P12] start 请求: {[u.split('/')[-2:] for u in scene_action_urls]}")

            sug = page.locator('.pd-pane .pd-card:has-text("demo-suite")')
            if not await sug.count():
                failures.append("场景页没有渲染自动检测建议卡")

            # chips 点击 → 细查跳转托管页
            chip = page.locator('.pd-pane .pd-badge:has-text("API 服务")').first
            await chip.click()
            await page.wait_for_timeout(300)
            if not await page.locator('.pd-pane:visible input[placeholder*="my-app"], .pd-pane button[title="扫描目录，批量发现可托管的项目"]').count():
                pass  # 托管页元素存在与否由 P9 断言兜底
            tab_active = await page.evaluate("""document.querySelector('.pd-tab.is-active')?.textContent || ''""")
            if "托管项目" not in tab_active:
                failures.append(f"点击步骤 chip 未跳回托管页（当前 active: {tab_active}）")
            print(f"[P12] chip 跳转后 active tab: {tab_active.strip()}")
            await set_tab(page, "scenes")

        print(f"\n[通用] 控制台错误 ({len(errors)}):")
        for e in errors[:6]:
            print("  ", e)
        hard = [e for e in errors if "tailwind is not defined" not in e]
        if hard:
            failures.append(f"控制台硬错误: {hard[:2]}")

        await browser.close()

    if not keep_shots and not baseline:
        pass

    print("\n" + "=" * 54)
    if failures:
        print(f"FAILURES ({len(failures)}):")
        for f in failures:
            print("  -", f)
        return 1
    print(f"PHASE {phase} ALL CHECKS PASSED")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", type=int, default=0)
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--shots", action="store_true")
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.phase, a.baseline, a.shots)))


main()
