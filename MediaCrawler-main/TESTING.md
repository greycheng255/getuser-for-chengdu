# 抖音私信发送测试用例

本文档说明了抖音私信发送功能的各种测试用例及其使用方法。

## 📁 测试文件说明

### 1. `test_outreach_automation.py` - 单元测试
**用途**: 测试私信发送核心功能的各个独立环节

**测试内容**:
- ✅ 消息发送和验证功能
- ✅ 消息内容不匹配处理
- ✅ 找不到发送按钮处理
- ✅ 找不到输入框处理

**运行方式**:
```bash
cd /home/ubuntu/getuser/MediaCrawler-main
python3 test_outreach_automation.py
```

**适用场景**: 快速验证代码逻辑是否正确

---

### 2. `test_integration_private_message.py` - 集成测试
**用途**: 测试完整的私信发送流程，包括任务创建、浏览器启动、消息发送、数据库记录等

**测试模式**:
1. **完整集成测试**: 需要真实浏览器和 Cookie，会实际执行私信发送
2. **模拟对话测试**: 快速验证逻辑，不需要真实浏览器
3. **运行所有测试**: 同时运行上述两种测试

**运行方式**:
```bash
cd /home/ubuntu/getuser/MediaCrawler-main
echo "2" | python3 test_integration_private_message.py
# 选项说明:
# 1 - 完整集成测试
# 2 - 模拟对话测试
# 3 - 运行所有测试
```

**适用场景**: 
- 开发完成后验证整体功能
- 部署前进行完整测试
- 调试私信发送问题

---

### 3. `test_conversation_flow.py` - 对话流程测试
**用途**: 模拟真实的对话场景，验证从打开对话框到消息显示的完整流程

**测试模式**:
1. **真实浏览器测试**: 使用 Playwright 启动真实浏览器，可以看到实际过程
2. **对话逻辑测试**: 模拟页面对象，快速验证对话逻辑
3. **运行所有测试**: 同时运行两种测试

**运行方式**:
```bash
cd /home/ubuntu/getuser/MediaCrawler-main
echo "2" | python3 test_conversation_flow.py
# 选项说明:
# 1 - 真实浏览器测试
# 2 - 对话逻辑测试
# 3 - 运行所有测试
```

**适用场景**:
- 验证对话流程是否符合预期
- 测试选择器是否能正确定位元素
- 查看实际的私信发送过程

---

##  快速开始

### 最简单的测试（推荐首次使用）

```bash
cd /home/ubuntu/getuser/MediaCrawler-main
python3 test_outreach_automation.py
```

这个测试不需要浏览器和 Cookie，可以快速验证代码逻辑。

### 完整的对话流程测试

```bash
cd /home/ubuntu/getuser/MediaCrawler-main
echo "2" | python3 test_conversation_flow.py
```

这个测试会模拟完整的对话流程，包括：
1. 打开私信对话框
2. 输入消息
3. 点击发送
4. 等待消息显示
5. 验证消息内容

### 真实环境测试（需要 Cookie）

1. 确保已有有效的抖音 Cookie：
   ```bash
   ls -la data/douyin_cookies.json
   ```

2. 运行真实浏览器测试：
   ```bash
   cd /home/ubuntu/getuser/MediaCrawler-main
   echo "1" | python3 test_conversation_flow.py
   ```

3. 观察浏览器窗口，查看实际的私信发送过程

4. 查看截图结果：
   ```bash
   ls -la data/conversation_test/
   ```

---

##  测试结果说明

### 成功标志
- ✅ 所有测试用例通过
- ✅ 消息发送成功并验证
- ✅ 数据库记录正确保存
- ✅ 截图文件生成正常

### 失败处理

如果测试失败，检查以下几点：

1. **Cookie 是否有效**
   ```bash
   cat data/douyin_cookies.json
   ```
   确保 Cookie 文件存在且格式正确

2. **依赖是否安装**
   ```bash
   pip3 list | grep playwright
   ```

3. **数据库是否正常**
   ```bash
   sqlite3 database/media_crawler.db "SELECT * FROM outreach_record LIMIT 5;"
   ```

4. **查看详细错误日志**
   测试失败时会输出详细的错误信息和堆栈跟踪

---

## 🔧 自定义测试

### 修改测试消息内容

在测试文件中找到 `test_content` 变量：

```python
test_content = "朋友 来啦！链接给你 👇\n\n一站式 AI 工具平台..."
```

### 修改测试用户

```python
task = create_outreach_task_data(
    user_id="your_test_user_id",
    sec_uid="your_test_sec_uid",
    platform="douyin",
    content="your_test_message",
    nickname="测试用户"
)
```

### 添加新的测试场景

在相应的测试文件中添加新的测试函数：

```python
async def test_your_scenario():
    """测试你的特定场景"""
    print("\n 测试：你的场景名称")
    # ... 测试代码
```

---

## 📝 常见问题

### Q: 为什么真实浏览器测试看不到浏览器窗口？
A: 确保在代码中设置 `headless=False`，并且系统支持 GUI 显示。

### Q: 测试失败提示 "Cookie 文件不存在"
A: 需要先手动登录抖音，然后在 Cookie 管理中心保存 Cookie。

### Q: 如何查看测试截图？
A: 截图保存在 `data/conversation_test/` 或 `data/test_screenshots/` 目录。

### Q: 测试运行很慢怎么办？
A: 可以先运行单元测试或模拟对话测试，这些不需要启动浏览器。

---

## 📞 技术支持

如有问题，请查看：
- 测试日志输出
- 错误堆栈跟踪
- 截图文件
- 数据库记录

祝测试顺利！🎉
