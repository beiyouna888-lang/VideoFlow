# 开发日志 Development Log

## **2026-5-11**

### 今日完成

- 完成项目初始化
- 创建 GitHub 仓库
- 上传基础代码文件
- 删除不需要的json档案

### 修改文件

- `zhihuishu.py`
- `README.md`

### 遇到的问题

```python
await el.click(force=True) #无法响应点击
```



### 解决方法

```python
box = await btn.bounding_box() 
cx = box['x'] + box['width'] / 2 #获取按钮的x轴
cy = box['y'] + box['height'] / 2 #获取按钮的y轴
await page.mouse.click(cx, cy) #模拟鼠标点击
```



## 2026-5-12

### 今日完成

- 修复了多选题无法正常关闭的问题
- 修复了除题目以外的其他弹窗无法正常关闭的问题

- 修复了题目提示框卡住program进程的问题


### 修改文件

- zuihuishu.py


### 遇到的问题

- 不同网课的网页框架不一样，换其他网课时program容易找不到视频播放的目录


### 解决方法