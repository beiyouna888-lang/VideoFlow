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


async def ensure_playing(page):
    """确保视频正在播放，并锁1.5倍速"""
    v = await page.query_selector("video")
    if not v:
        return False
    try:
        try:
            await v.evaluate("v => { v.playbackRate = 1.4; v.muted = true; }")
        except:
            pass

        paused = await v.evaluate("v => v.paused")
        if not paused:
            return True  # 已经在播放

        print("   ▶️ 尝试播放并提速...")

        try:
            await v.evaluate("v => v.play()")
            await asyncio.sleep(1)
            if not await v.evaluate("v => v.paused"):
                print("   ✅ 播放成功 (已锁定 1.5 倍速 + 静音)")
                return True
        except:
            pass

        player = await page.query_selector('.able-player-container')
        if player:
            box = await player.bounding_box()
            if box:
                # 点正中间
                x = box['x'] + box['width'] / 2
                y = box['y'] + box['height'] / 2
                await page.mouse.click(x, y)
                print(f"   ✅ 点击播放器 ({x:.0f}, {y:.0f})")
                await asyncio.sleep(2)
                if not await v.evaluate("v => v.paused"):
                    return True

        for sel in ['.bigPlayButton', '.vjs-big-play-button', '.playButton']:
            btn = await page.query_selector(sel)
            if btn:
                try:
                    await btn.evaluate("el => el.click()")
                    await asyncio.sleep(1)
                    if not await v.evaluate("v => v.paused"):
                        print(f"   ✅ 点击 {sel} 成功")
                        return True
                except:
                    continue

        return False
    except Exception as e:
        print(f"   ⚠️ ensure_playing 报错: {e}")
        return False


async def handle_question(page):
    for ctx in [page] + page.frames:
        try:
            # 抓取弹窗元素
            d = await find_el(ctx, [
                '[class*="dialog"]', '[class*="modal"]', '.el-dialog', '.el-overlay',
                '[class*="question"]', '[class*="popup"]', '[class*="mask"]'
            ])
            if not d: continue
            t = (await d.inner_text() or "").strip()
            if len(t) < 10: continue

           # ========== 1. 专门对付 AI 小智 ==========
            if "AI助教小智" in t or "不会影响" in t or "小智给你出题啦" in t:
                print(f"\n🤖 发现 [AI助教小智] 弹窗！...")
                
                clicked = False
                # 策略：直接找屏幕上的文字，获取绝对物理坐标，用虚拟鼠标去点屏幕像素！
                for target_text in ["A. 对", "A.", "对", "A", "正确"]:
                    try:
                        # 模糊查找包含这些文字的元素
                        els = await d.query_selector_all(f'text="{target_text}"')
                        for el in els:
                            box = await el.bounding_box()
                            # 确保该文字在屏幕上是可见的（有长宽）
                            if box and box['width'] > 0 and box['height'] > 0:
                                # 计算文字的正中心坐标
                                center_x = box['x'] + box['width'] / 2
                                center_y = box['y'] + box['height'] / 2
                                
                                # 将鼠标平滑移动过去（纯物理操作，100% 模拟真人）
                                await page.mouse.move(center_x, center_y)
                                await asyncio.sleep(0.2)
                                # 狙击文字中心
                                await page.mouse.click(center_x, center_y)
                                
                                # 保险起见：往文字左边偏移 15 像素（通常是圆圈所在的位置）再点一次
                                await page.mouse.click(box['x'] - 15, center_y)
                                
                                print(f"   🎯 : '{target_text}'")
                                clicked = True
                                break
                    except Exception as e:
                        continue
                    
                    if clicked: break

                print(" ⏳ 等待 2 秒让系统出答案...")
                await asyncio.sleep(2)
                
                print(" 🚪 正在关闭弹窗...")
                # 同样用屏幕坐标法关闭弹窗，无视任何弹窗遮罩层
                try:
                    close_btns = await d.query_selector_all('text="关闭"')
                    for btn in close_btns:
                        box = await btn.bounding_box()
                        if box and box['width'] > 0:
                            cx = box['x'] + box['width'] / 2
                            cy = box['y'] + box['height'] / 2
                            await page.mouse.click(cx, cy)
                            print("   ✅ 已通过坐标点击屏幕上的[关闭]按钮")
                            break
                except: pass
                
                # 备用：点右上角 X 的坐标
                try:
                    xs = await d.query_selector_all('.el-icon-close, .el-dialog__headerbtn, [class*="close"]')
                    for x_el in xs:
                        box = await x_el.bounding_box()
                        if box and box['width'] > 0:
                            await page.mouse.click(box['x'] + box['width']/2, box['y'] + box['height']/2)
                            break
                except: pass
                
                await asyncio.sleep(3)
                return True
            # ========================================
            
            # ========== 2. 正常题目的处理逻辑 ==========
            if any(kw in t for kw in ["单选题", "多选题", "判断题", "请选择", "作答"]):
                print(f"\n📌 遇到常规题目: {t[:60]}...")
                opts = []
                seen = set()
                for sel in ['label', 'li', '[class*="option"]', '.el-radio', '.el-checkbox']:
                    for el in await d.query_selector_all(sel):
                        try:
                            if await el.is_visible():
                                txt = (await el.text_content() or "").strip()
                                if txt and len(txt) < 300 and txt not in seen:
                                    seen.add(txt); opts.append(el)
                        except: continue
                
                if not opts:
                    if await click_btn(ctx, ["关闭", "我知道了", "不再提示", "确定"]): return True
                    continue

                for i, opt in enumerate(opts):
                    txt = (await opt.text_content() or "").strip()[:40]
                    print(f"   🔄 尝试选项 {i+1}: {txt}")
                    try:
                        await opt.evaluate("el => el.closest('label,.el-radio,.el-checkbox')?.click()||el.click()")
                    except:
                        try: await opt.click(force=True)
                        except: continue

                    await asyncio.sleep(1)
                    await click_btn(ctx, ["确定", "提交"])
                    await asyncio.sleep(1.5)

                    nd = await find_el(ctx, ['.el-message-box', '[class*="dialog"]', '.el-overlay'])
                    if not nd:
                        print("   ✅ 正确!"); return True
                    
                    nt = (await nd.inner_text() or "")
                    if "错误" in nt or "不正确" in nt:
                        print("   ❌ 错误, 尝试下一个选项")
                        await click_btn(ctx, ["确定", "关闭", "我知道了"])
                        await asyncio.sleep(1)
                        continue
                    
                    await click_btn(ctx, ["关闭", "确定"])
                    return True

            # 保底：乱七八糟的提示框统统关掉
            if await click_btn(ctx, ["关闭", "确定", "我知道了", "不再提示"]):
                return True
                
        except Exception as e:
            continue
            
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
                                
                                if elapsed > 10:
                                    print("\n⚠️ 等待超时，服务器未发蓝勾，尝试重新播放补全进度...")
                                    try:
                                        await page.evaluate("() => { document.querySelectorAll('video').forEach(v => v.play()); }")
                                    except: pass
                                    last_video_change = current_time_val
                            else:
                                # 视频中途意外暂停（比如AI弹窗刚关掉还没来得及恢复）
                                elapsed = current_time_val - last_video_change
                                if elapsed > 15:
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
