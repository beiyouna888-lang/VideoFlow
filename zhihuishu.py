"""
智慧树脚本
"""

import asyncio, json, os, sys, re, time, random
from playwright.async_api import async_playwright

async def human_delay(min_s=0.3, max_s=1.2):
    await asyncio.sleep(random.uniform(min_s, max_s))


COURSE_URL = "https://studyvideoh5.zhihuishu.com/stuStudy?recruitAndCourseId=4e59515b40584859454a585958435b4750"
STATE_FILE = "zhihuishu_state.json"
PROGRESS_FILE = "zhihuishu_progress.json"


async def load_progress():
    """加载播放进度"""
    try:
        if os.path.exists(PROGRESS_FILE):
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except:
        pass
    return {"last_idx": -1, "last_name": ""}


async def save_progress(idx, name):
    """保存播放进度"""
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_idx": idx, "last_name": name, "updated": time.strftime("%m-%d %H:%M")},
                      f, ensure_ascii=False, indent=2)
    except:
        pass


async def login(_, page):
    print("🔐 登录...")
    await page.goto("https://onlineweb.zhihuishu.com/", timeout=60000)
    await page.wait_for_timeout(3000)
    input("📌 登录后按 Enter 继续...")
    await page.context.storage_state(path=STATE_FILE)
    print(f"✅ 已保存 {STATE_FILE}")


async def find_el(ctx, selectors):
    for s in selectors:
        try:
            e = await ctx.query_selector(s)
            if e and await e.is_visible():
                return e
        except:
            continue
    return None


async def click_btn(ctx, texts):
    for t in texts:
        for s in [f'button:has-text("{t}")', f'div:has-text("{t}")',
                  f'span:has-text("{t}")', f'a:has-text("{t}")']:
            try:
                b = await ctx.query_selector(s)
                if b and await b.is_visible():
                    await b.click()
                    return t
            except:
                continue
    return None


async def ensure_playing(page,rate=1.4):
    """确保视频正在播放并锁1.4倍速"""
    v = await page.query_selector("video")
    if not v:
        return False
    try:
        try:
            await v.evaluate("(v, rate) => v.playbackRate = rate", rate)
        except:
            pass

        paused = await v.evaluate("v => v.paused")
        if not paused:
            return True  # 已经在播放
        
        print("   ▶️ 尝试播放并提速...")

        try:
            # 尝试JS播放
            ok = await v.evaluate(
                """async (v, rate) => {
                    try {
                        v.muted = true;
                        v.playbackRate = rate;
                        await v.play();
                        return !v.paused;
                    } catch (e) {
                        return false;
                    }
                }""",
                rate
            )

            if ok:
                print(f"   ✅ 播放成功，已设置 {rate} 倍速 + 静音")
                return True

            # 尝试点击播放器中心
            player = await page.query_selector(".able-player-container")
            if player:
                box = await player.bounding_box()
                if box:
                    x = box["x"] + box["width"] / 2
                    y = box["y"] + box["height"] / 2
                    await page.mouse.click(x, y)
                    print(f"   ✅ 点击播放器 ({x:.0f}, {y:.0f})")
                    await asyncio.sleep(1)

                    await v.evaluate("(v, rate) => v.playbackRate = rate", rate)

                    if not await v.evaluate("v => v.paused"):
                        return True
        except:
            pass

        return False
    except Exception as e:
        print(f"   ⚠️ ensure_playing 报错: {e}")
        return False

async def handle_question(page):
    """先检测弹窗，再判断是否题目：是题目就随便选一个答案，不是题目就关闭"""

    # ========== 0. 先清理一些常见非题目弹窗 ==========
    try:
        await page.evaluate("""() => {
            let btns = document.querySelectorAll('button, .el-button, .el-dialog__headerbtn');
            btns.forEach(btn => {
                let txt = btn.innerText || "";
                if (
                    txt.includes("下次再说") ||
                    txt.includes("已绑定") ||
                    txt.includes("不再提示") ||
                    txt.includes("我知道了")
                ) {
                    btn.click();
                }
            });
        }""")
    except:
        pass

    # ========== 1. 遍历主页面 + iframe ==========
    for ctx in [page] + page.frames:
        try:
            # 先找有没有弹窗，不管是不是题目
            d = await find_real_popup(ctx)
            if not d:
                continue

            print("\n⚠️ 检测到弹窗")

            # 获取弹窗文字
            popup_text = ""
            try:
                if d:
                    popup_text = (await d.inner_text() or "").strip()
                else:
                    popup_text = await ctx.evaluate("() => document.body.innerText || ''")
            except:
                popup_text = ""

            # ========== 2. 判断这个弹窗是不是题目 ==========
            question_keywords = [
                "单选题",
                "多选题",
                "判断题",
                "题目",
                "未做答的弹题不能关闭"
            ]

            is_question = any(kw in popup_text for kw in question_keywords)

            # 再用选项结构辅助判断
            option_count = 0
            try:
                root = d if d else ctx
                options = await root.query_selector_all(
                    'label.el-radio, label.el-checkbox, .el-radio, .el-checkbox, '
                    '.topic-item, .answerItem'
                )

                for opt in options:
                    try:
                        if await opt.is_visible():
                            txt = (await opt.text_content() or "").strip()
                            if txt and len(txt) < 300:
                                option_count += 1
                    except:
                        continue

                if option_count >= 2:
                    is_question = True
            except:
                pass

            # ========== 3. 如果是题目：随便选一个答案 ==========
            if is_question:
                print("   📌 判断为题目弹窗，准备随便选择一个答案")

                await close_unanswered_warning(page, ctx)

                clicked = False
                root = d if d else ctx

                # 3.1 优先找选项按钮/选项行
                try:
                    option_selectors = [
                        'label.el-radio',
                        'label.el-checkbox',
                        '.el-radio',
                        '.el-checkbox',
                        '.topic-item',
                        '.answerItem',
                        '[class*="option"]',
                        'li'
                    ]

                    all_options = []

                    for sel in option_selectors:
                        try:
                            els = await root.query_selector_all(sel)
                            for el in els:
                                try:
                                    if not await el.is_visible():
                                        continue

                                    txt = (await el.text_content() or "").strip()

                                    # 过滤掉按钮类文字
                                    if any(x in txt for x in ["确定", "提交", "关闭", "取消", "下一题"]):
                                        continue

                                    box = await el.bounding_box()
                                    if box and box["width"] > 0 and box["height"] > 0:
                                        all_options.append(el)
                                except:
                                    continue
                        except:
                            continue

                    if all_options:
                        opt = random.choice(all_options)
                        box = await opt.bounding_box()

                        # 尽量点左侧圆圈位置
                        x = box["x"] + 15
                        y = box["y"] + box["height"] / 2

                        await page.mouse.click(x, y)
                        print(f"   🎯 已随机点击一个选项 ({x:.0f}, {y:.0f})")
                        clicked = True

                except Exception as e:
                    print(f"   ⚠️ 选项点击失败: {e}")

                # 3.2 兜底：找 A / B / 对 / 正确 这些文字
                if not clicked:
                    for target_text in ["A. ", "A.", "A", "对", "正确", "是"]:
                        try:
                            els = await ctx.query_selector_all(f'text="{target_text}"')
                            for el in els:
                                box = await el.bounding_box()
                                if box and box["width"] > 0 and box["height"] > 0:
                                    await page.mouse.click(
                                        box["x"] + box["width"] / 2,
                                        box["y"] + box["height"] / 2
                                    )
                                    print(f"   🎯 兜底点击答案: {target_text}")
                                    clicked = True
                                    break
                        except:
                            pass

                        if clicked:
                            break

                await asyncio.sleep(1)

                # 3.3 点击提交/确定
                try:
                    if await click_btn(ctx, ["提交", "确定", "完成"]):
                        print("   ✅ 已提交答案")
                        await asyncio.sleep(1.5)
                except:
                    pass

                # 3.4 提交后尝试关闭
                try:
                    xs = await ctx.query_selector_all(
                        '.el-icon-close, .el-dialog__headerbtn, [class*="close"]'
                    )
                    for x_el in xs:
                        box = await x_el.bounding_box()
                        if box and box["width"] > 0 and box["height"] > 0:
                            await page.mouse.click(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2
                            )
                            print("   ✅ 已点击右上角 X")
                            await asyncio.sleep(1)
                            return True
                except:
                    pass

                return True

            # ========== 4. 如果不是题目：直接关闭 ==========
            else:
                print("   🚪 判断为普通弹窗，直接关闭")

                closed = False

                try:
                    if await click_btn_in_popup(
                        page,
                        d,
                        ["关闭", "确定", "我知道了", "不再提示", "下次再说", "取消"]
                        ):
                        print("   ✅ 已关闭普通弹窗")
                        await asyncio.sleep(1)
                        closed = True
                except Exception as e:
                    print(f"   ⚠️ 关闭普通弹窗失败: {e}")

                # 兜底点 X
                if not closed:
                    closed = await close_popup_by_x(page, ctx, d)

                # 最后兜底 ESC
                if not closed:
                    await page.keyboard.press("Escape")
                    print("   ⌨️ 已按 ESC 尝试关闭普通弹窗")
                    await asyncio.sleep(1)
                    return True

                print("   ✅ 已关闭普通弹窗")
                return True

        except Exception as e:
            continue

    return False

async def find_real_popup(ctx):
    """只检测真正显示在屏幕中间的弹窗，避免误判隐藏 DOM"""
    handle = await ctx.evaluate_handle("""
    () => {
        const roots = document.querySelectorAll(`
            .el-dialog__wrapper,
            .el-message-box__wrapper,
            .el-dialog,
            .el-message-box,
            .tm_dialog,
            [role="dialog"]
        `);

        const vw = window.innerWidth;
        const vh = window.innerHeight;

        for (const root of roots) {
            const target =
                root.querySelector('.el-dialog, .el-message-box, .tm_dialog, [role="dialog"]')
                || root;

            const rs = window.getComputedStyle(root);
            const ts = window.getComputedStyle(target);
            const r = target.getBoundingClientRect();

            const visible =
                rs.display !== 'none' &&
                rs.visibility !== 'hidden' &&
                ts.display !== 'none' &&
                ts.visibility !== 'hidden' &&
                parseFloat(ts.opacity || '1') > 0.05 &&
                r.width > 250 &&
                r.height > 100 &&
                r.right > 0 &&
                r.bottom > 0 &&
                r.left < vw &&
                r.top < vh;

            if (!visible) continue;

            const centerX = r.left + r.width / 2;
            const centerY = r.top + r.height / 2;

            const nearCenter =
                Math.abs(centerX - vw / 2) < vw * 0.35 &&
                Math.abs(centerY - vh / 2) < vh * 0.35;

            if (!nearCenter) continue;

            return target;
        }

        return null;
    }
    """)

    el = handle.as_element()
    return el

async def click_btn_in_popup(page, popup, texts):
    """只在当前弹窗里面找按钮，并用坐标点击"""

    for text in texts:
        selectors = [
            f'button:has-text("{text}")',
            f'.el-button:has-text("{text}")',
            f'a:has-text("{text}")',
            f'span:has-text("{text}")',
            f'div:has-text("{text}")',
            f'text="{text}"',
        ]

        for sel in selectors:
            try:
                btns = await popup.query_selector_all(sel)

                for btn in btns:
                    try:
                        if not await btn.is_visible():
                            continue

                        box = await btn.bounding_box()
                        if not box or box["width"] <= 0 or box["height"] <= 0:
                            continue

                        x = box["x"] + box["width"] / 2
                        y = box["y"] + box["height"] / 2

                        await page.mouse.click(x, y)
                        print(f"   ✅ 已点击弹窗按钮: {text}")
                        await asyncio.sleep(0.8)
                        return True

                    except:
                        continue

            except:
                continue

    return False

async def close_unanswered_warning(page, ctx):
    """关闭‘未做答的弹题不能关闭’提示框"""
    try:
        has_warning = await ctx.evaluate("""() => {
            return document.body && document.body.innerText.includes("未做答的弹题不能关闭");
        }""")

        if not has_warning:
            return False

        print("   ⚠️ 检测到提示框")

        # 优先点提示框右上角 X
        selectors = [
            ".el-message-box__headerbtn",
            ".el-message-box__close",
            ".el-icon-close",
            ".el-message-box [class*='close']",
            "text=×"
        ]

        for sel in selectors:
            try:
                xs = await ctx.query_selector_all(sel)
                for x in xs:
                    if await x.is_visible():
                        box = await x.bounding_box()
                        if box:
                            await page.mouse.click(
                                box["x"] + box["width"] / 2,
                                box["y"] + box["height"] / 2
                            )
                            print("   ✅ 已关闭未答题提示框")
                            await asyncio.sleep(0.8)
                            return True
            except:
                pass

    except Exception as e:
        print(f"   ⚠️ 关闭未答题提示失败: {e}")
        return False

async def close_popup_by_x(page, ctx, popup):
    """专门关闭只有右上角 X 的普通弹窗"""

    # 先拿弹窗位置
    pbox = await popup.bounding_box()
    if not pbox:
        return False

    # 1. 优先找常见 X 按钮
    x_selectors = [
        ".el-dialog__headerbtn",
        ".el-dialog__close",
        ".el-icon-close",
        "i[class*='close']",
        "span[class*='close']",
        "button[class*='close']",
        "[class*='close']",
        "text=×",
    ]

    for sel in x_selectors:
        try:
            xs = await ctx.query_selector_all(sel)

            for x_el in xs:
                try:
                    if not await x_el.is_visible():
                        continue

                    box = await x_el.bounding_box()
                    if not box or box["width"] <= 0 or box["height"] <= 0:
                        continue

                    cx = box["x"] + box["width"] / 2
                    cy = box["y"] + box["height"] / 2

                    # 只点弹窗右上区域，避免点错页面其它 X
                    in_popup_top_right = (
                        pbox["x"] < cx < pbox["x"] + pbox["width"] and
                        pbox["y"] < cy < pbox["y"] + 90 and
                        cx > pbox["x"] + pbox["width"] * 0.7
                    )

                    if not in_popup_top_right:
                        continue

                    await page.mouse.click(cx, cy)
                    print(f"   ✅ 已点击弹窗右上角 X: {sel}")
                    await asyncio.sleep(1)
                    return True

                except:
                    continue

        except:
            continue

    # 2. 兜底：直接按弹窗右上角坐标点
    try:
        x = pbox["x"] + pbox["width"] - 35
        y = pbox["y"] + 30

        await page.mouse.click(x, y)
        print(f"   ✅ 已按坐标点击弹窗右上角 X ({x:.0f}, {y:.0f})")
        await asyncio.sleep(1)
        return True

    except:
        return False
    
async def click_next_video(page):
    """根据网页真实状态，点下一个【未播放完成】的视频章节并播放"""
    print("   🔍 正在扫描未完成的视频...")
    try:
        chapters = await page.query_selector_all('li.clearfix.video')
        total = len(chapters)
        
        if total == 0:
            print("   ⚠️ 找不到视频章节列表，请检查网页侧边栏结构！")
            return False

        target_chapter = None
        target_idx = -1

        for i, chapter in enumerate(chapters):
            text = await chapter.inner_text() or ""
            is_finished_by_text = "100%" in text or "100.0%" in text
            finished_icon = await chapter.query_selector('.time_icofinish')
            
            if not is_finished_by_text and not finished_icon:
                class_name = await chapter.get_attribute("class") or ""
                if "lock" not in class_name:
                    target_chapter = chapter
                    target_idx = i
                    break 

        if target_chapter:
            txt = (await target_chapter.inner_text() or "").strip()[:50].replace('\n', ' ')
            print(f"   ➡️ 找到未完成视频 [{target_idx}]: {txt}")

            # ========== 核心修改点：使用带 force 的原生安全点击 ==========
            print("   🖱️ 尝试点击该章节...")
            try:
                # 尽量点元素的左上角一点点，避开中间可能存在的遮挡物，force=True 强制点击但不丢失 isTrusted
                await target_chapter.click(position={"x": 20, "y": 20}, force=True)
            except Exception as click_err:
                print(f"   ⚠️ 点击报错: {click_err}")
            
            print("   ⏳ 等待 8 秒让视频播放器重新加载...")
            await asyncio.sleep(8) # 延长一点时间，真人换课没那么快
            # ==========================================================
            
            ok = await ensure_playing(page)
            if ok:
                await save_progress(target_idx, txt)
                print("   ✅ 新视频已成功开始播放！")
            return True
        else:
            print("   ✅ 所有已解锁的视频似乎都已经播完了（进度 100%）!")
            return False
            
    except Exception as e:
        print(f"   ⚠️ click_next_video 报错: {e}")
        return False
    
async def main():
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,
                args=["--window-size=1366,768", "--disable-blink-features=AutomationControlled"]
            )
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="zh-CN",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )

            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            if "cookies" in state:
                await context.add_cookies(state["cookies"])
            print("✅ 状态已加载")

            page = await context.new_page()
            page.on("dialog", lambda d: asyncio.ensure_future(
                asyncio.sleep(0.1) or d.accept()
            ))
            
            # 隐藏 webdriver 特征
            page = await context.new_page()
            page.on("dialog", lambda d: asyncio.ensure_future(
                asyncio.sleep(0.1) or d.accept()
            ))
            
            # ========== 核心修改点：应用专业隐身衣 ==========
            await page.add_init_script("""
                // 1. 彻底抹除 webdriver 痕迹
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                
                // 2. 伪装成普通 Chrome 浏览器（补全 csi 和 loadTimes 方法）
                window.chrome = {
                    runtime: {},
                    app: {},
                    csi: function() {},
                    loadTimes: function() {}
                };
                
                // 3. 伪装通知权限，绕过无头浏览器权限特征检测
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
                
                // 4. 伪装真实的插件列表（随便写几个数字骗不过现代风控了，必须写真的结构）
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [{
                        description: "Portable Document Format",
                        filename: "internal-pdf-viewer",
                        length: 1,
                        name: "Chrome PDF Plugin"
                    }]
                });
                
                // 5. 伪装系统语言
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en', 'en-US']
                });
            """)
            # ========================================

            await page.goto(COURSE_URL, timeout=120000, wait_until="domcontentloaded")
            # ============================================

            await page.goto(COURSE_URL, timeout=120000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

            # 关掉温馨提示
            await click_btn(page, ["不再提示", "我知道了"])
            await page.wait_for_timeout(1000)

            # 点击第一个视频
            await click_next_video(page)
            await asyncio.sleep(4)

            # 尝试播放
            v = await page.query_selector("video")
            if v:
                try:
                    await v.click()
                    await asyncio.sleep(1)
                    await v.evaluate("v => v.play()")
                    print("▶️ 播放中")
                except:
                    pass

            print("\n👀 监控中...\n")

            last_video_change = time.time()
            no_video_count = 0

            while True:
                try:
                    await handle_question(page)

                    # ========== 1. 核心大招：蓝勾质检（精准打击） ==========
                    try:
                        # 【核心修复】必须加 .video 限定，防止错抓到网页顶部的无关标签！
                        current_chap = await page.query_selector('li.video.currents, li.video[class*="current"], li.video[class*="active"]')
                        if current_chap:
                            chap_text = await current_chap.inner_text() or ""
                            has_check = await current_chap.query_selector('.time_icofinish')
                            
                            # 只要有蓝勾，或者显示100%，一秒都不多待，直接切走！
                            if has_check or "100%" in chap_text or "100.0%" in chap_text:
                                print(f"\n✨ 当前章节 [{chap_text[:15].strip()}] 已打蓝勾！")
                                print("⏭️ 切换，前往下一个视频...")
                                await click_next_video(page)
                                last_video_change = time.time()
                                await asyncio.sleep(5)
                                continue
                    except Exception as e:
                        pass
                    # ===================================================

                    # ========== 2. 视频状态监控（防错位真身识别版） ==========
                    # 【核心修复】用 JS 遍历所有 video 标签，只盯住“时长最长”的那个真正的课程视频
                    video_state = await page.evaluate("""() => {
                        let videos = Array.from(document.querySelectorAll('video'));
                        if (videos.length === 0) return null;
                        // 按时长从长到短排序，拿第一个（绝对是主课视频，避开假标签）
                        let mainVideo = videos.sort((a, b) => (b.duration || 0) - (a.duration || 0))[0];
                        return {
                            paused: mainVideo.paused,
                            ct: mainVideo.currentTime || 0,
                            dur: mainVideo.duration || 0
                        };
                    }""")
                    
                    current_time_val = time.time()

                    if video_state:
                        no_video_count = 0
                        paused = video_state['paused']
                        ct = video_state['ct']
                        dur = video_state['dur']

                        if paused and dur > 0:
                            remaining = dur - ct
                            if 0 <= remaining < 2 or ct >= dur:
                                elapsed = current_time_val - last_video_change
                                print(f"\r⏳ 视频已到底，原地等待服务器发放蓝勾... (已等 {elapsed:.0f}s) ", end="")
                                
                                if elapsed > 15: # 给服务器多一点判定时间
                                    print("\n⚠️ 等待超时，服务器未发蓝勾，尝试倒退 15 秒重新播放补全时长...")
                                    try:
                                        # 核心修复：视频到底后直接 play() 是无效的，必须往回拨一段进度才能继续发心跳包
                                        await page.evaluate("""() => { 
                                            document.querySelectorAll('video').forEach(v => { 
                                                v.currentTime = Math.max(0, v.duration - 15); 
                                                v.play(); 
                                            }); 
                                        }""")
                                    except: pass
                                    last_video_change = current_time_val
                            else:
                                # 视频中途意外暂停（比如AI弹窗刚关掉还没来得及恢复）
                                elapsed = current_time_val - last_video_change
                                if elapsed > 5:
                                    print(f"\n📴 视频中途意外暂停 (当前进度: {ct:.0f}s / {dur:.0f}s)")
                                    print("   🔧 重新播放...")
                                    await ensure_playing(page)
                                    last_video_change = current_time_val
                        else:
                            # 视频正在顺利播放中，不断刷新活跃时间
                            last_video_change = current_time_val
                    else:
                        no_video_count += 1
                        if no_video_count > 5:
                            print("\n🔍 页面中没有找到有效视频，尝试点击下一节...")
                            await click_next_video(page)
                            await asyncio.sleep(3)
                            no_video_count = 0

                except Exception as e:
                    # 屏蔽杂乱无章的细小报错，保持终端干净
                    pass
                
                await asyncio.sleep(3)

    except KeyboardInterrupt:
        print("\n👋 退出")
    except Exception as e:
        print(f"❌ {e}")
        import traceback; traceback.print_exc()
        input("按 Enter 退出...")
    finally:
        if browser: await browser.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--login":
        async def do_login():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False, args=["--window-size=1366,768"])
                context = await browser.new_context(viewport={"width": 1366, "height": 768}, locale="zh-CN")
                page = await context.new_page()
                await login(context, page)
                await browser.close()
        asyncio.run(do_login())
    else:
        asyncio.run(main())
