#!/usr/bin/env python3
"""
GEO优化完整流程自动测试
测试网站: www.zhiranrome.com
关键词: 家居设计
"""

import requests
import json
import time
from datetime import datetime

# API配置
API_BASE = "http://localhost:5001/api"
BRAND_NAME = "织然家具"
WEBSITE = "www.zhiranrome.com"
KEYWORD = "家居设计"

class GEOWorkflowTester:
    """GEO工作流测试器"""

    def __init__(self):
        self.results = []
        self.ai_task_id = None
        self.publish_task_id = None

    def log(self, step, message, data=None):
        """记录日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = {
            "time": timestamp,
            "step": step,
            "message": message,
            "data": data
        }
        self.results.append(log_entry)
        print(f"[{timestamp}] {step}: {message}")
        if data:
            print(f"  ↳ 数据: {json.dumps(data, ensure_ascii=False, indent=2)[:200]}...")

    # ==================== 阶段1: AI内容生成 ====================

    def test_ai_content_generation(self):
        """测试AI内容生成"""
        self.log("阶段1", "开始AI内容生成测试")

        # 1.1 生成文章
        self.log("1.1", "生成GEO优化文章", {"keyword": KEYWORD})

        article_prompt = f"""
        为品牌"{BRAND_NAME}"(官网: {WEBSITE})生成一篇关于"{KEYWORD}"的GEO优化文章。

        要求:
        1. 标题包含关键词和品牌名
        2. 内容专业、有深度，2000字以上
        3. 包含品牌介绍和优势
        4. 添加FAQ部分
        5. 使用Schema.org结构化数据格式

        文章结构:
        - H1标题
        - 引言
        - 正文(多个H2小节)
        - FAQ部分
        - 结语
        """

        try:
            response = requests.post(f"{API_BASE}/content/generate", json={
                "keyword": KEYWORD,
                "content_type": "article",
                "target_length": 2000,
                "include_faq": True,
                "include_schema": True,
                "brand_name": BRAND_NAME,
                "website": WEBSITE
            }, timeout=120)

            if response.status_code == 200:
                data = response.json()
                self.log("1.1", "文章生成成功", {"content_length": len(data.get("content", ""))})
                return data.get("content")
            else:
                self.log("1.1", f"文章生成失败: {response.status_code}", {"error": response.text})
                return None
        except Exception as e:
            self.log("1.1", f"文章生成异常: {str(e)}")
            return None

    def test_ai_task_creation(self):
        """测试AI任务创建"""
        self.log("1.2", "创建AI生成任务")

        try:
            response = requests.post(f"{API_BASE}/ai-tasks/create-from-plan", json={
                "plan_id": 1,
                "task_types": ["article_generation", "faq_generation", "schema_markup"],
                "keywords": [KEYWORD, "定制家具", "全屋定制"]
            }, timeout=30)

            if response.status_code == 200:
                data = response.json()
                self.ai_task_id = data.get("tasks", [{}])[0].get("id")
                self.log("1.2", "AI任务创建成功", {"task_id": self.ai_task_id})
                return True
            else:
                self.log("1.2", f"任务创建失败: {response.status_code}")
                return False
        except Exception as e:
            self.log("1.2", f"任务创建异常: {str(e)}")
            return False

    # ==================== 阶段2: 一键分发 ====================

    def test_publish_platforms(self):
        """测试发布平台列表"""
        self.log("阶段2", "开始一键分发测试")
        self.log("2.1", "获取发布平台列表")

        try:
            response = requests.get(f"{API_BASE}/publish/platforms", timeout=10)

            if response.status_code == 200:
                data = response.json()
                platforms = data.get("platforms", [])
                self.log("2.1", f"获取到 {len(platforms)} 个平台", {
                    "platforms": [p["name"] for p in platforms]
                })
                return platforms
            else:
                self.log("2.1", f"获取平台列表失败: {response.status_code}")
                return []
        except Exception as e:
            self.log("2.1", f"获取平台列表异常: {str(e)}")
            return []

    def test_quick_publish(self):
        """测试快速发布"""
        self.log("2.2", "测试快速发布功能")

        # 模拟内容
        test_content = f"""
# {BRAND_NAME} - 专业的{KEYWORD}服务

{BRAND_NAME}({WEBSITE})是一家专注于{KEYWORD}的定制家具品牌。

## 我们的优势

1. 个性化设计
2. 环保材料
3. 专业安装
4. 售后保障

## FAQ

**Q: {KEYWORD}需要多少钱？**
A: 根据具体需求报价，欢迎咨询。

**Q: 定制周期多长？**
A: 一般30-45天。
        """

        try:
            response = requests.post(f"{API_BASE}/publish/quick", json={
                "content_id": self.ai_task_id or 1,
                "title": f"{BRAND_NAME} - {KEYWORD}专家",
                "content": test_content,
                "content_type": "article",
                "keywords": [KEYWORD, "定制家具", BRAND_NAME],
                "platforms": ["website_blog", "website_faq"]  # 只发布到官网
            }, timeout=30)

            if response.status_code == 200:
                data = response.json()
                self.publish_task_id = data.get("task_id")
                self.log("2.2", "快速发布成功", {"task_id": self.publish_task_id})
                return True
            else:
                self.log("2.2", f"快速发布失败: {response.status_code}", {"error": response.text})
                return False
        except Exception as e:
            self.log("2.2", f"快速发布异常: {str(e)}")
            return False

    # ==================== 阶段3: 效果监控 ====================

    def test_monitoring_dashboard(self):
        """测试监控仪表板"""
        self.log("阶段3", "开始效果监控测试")
        self.log("3.1", "获取监控仪表板数据")

        try:
            response = requests.get(f"{API_BASE}/monitoring/dashboard?days=7", timeout=10)

            if response.status_code == 200:
                data = response.json()
                dashboard = data.get("dashboard", {})
                self.log("3.1", "仪表板数据获取成功", {
                    "ai_citation": dashboard.get("ai_citation"),
                    "traffic": dashboard.get("traffic")
                })
                return True
            else:
                self.log("3.1", f"仪表板数据获取失败: {response.status_code}")
                return False
        except Exception as e:
            self.log("3.1", f"仪表板数据获取异常: {str(e)}")
            return False

    def test_search_rank_check(self):
        """测试搜索排名检查"""
        self.log("3.2", f"检查关键词排名: {KEYWORD}")

        try:
            response = requests.post(f"{API_BASE}/monitoring/search-rank/check", json={
                "keyword": f"{BRAND_NAME} {KEYWORD}",
                "search_engine": "baidu"
            }, timeout=30)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                self.log("3.2", f"排名检查完成，找到 {len(results)} 条结果")

                # 检查是否有品牌网站
                brand_found = any(WEBSITE in r.get("url", "") for r in results)
                self.log("3.2", f"品牌网站{'已' if brand_found else '未'}在搜索结果中")
                return True
            else:
                self.log("3.2", f"排名检查失败: {response.status_code}")
                return False
        except Exception as e:
            self.log("3.2", f"排名检查异常: {str(e)}")
            return False

    def test_ai_citation_check(self):
        """测试AI引用检查"""
        self.log("3.3", "检查AI引用情况")

        test_queries = [
            f"{KEYWORD}哪个品牌好",
            f"{BRAND_NAME}怎么样",
            "定制家具推荐"
        ]

        for query in test_queries:
            try:
                response = requests.post(f"{API_BASE}/monitoring/ai-citation/check", json={
                    "platform": "doubao",
                    "query": query,
                    "brand_name": BRAND_NAME
                }, timeout=30)

                if response.status_code == 200:
                    data = response.json()
                    result = data.get("result", {})
                    mentioned = result.get("mentioned", False)
                    self.log("3.3", f"查询'{query}': {'✅ 已提及' if mentioned else '❌ 未提及'}")
                else:
                    self.log("3.3", f"查询'{query}'失败: {response.status_code}")
            except Exception as e:
                self.log("3.3", f"查询'{query}'异常: {str(e)}")

        return True

    # ==================== 综合测试 ====================

    def run_full_test(self):
        """运行完整测试"""
        print("=" * 60)
        print(f"GEO优化完整流程自动测试")
        print(f"测试网站: {WEBSITE}")
        print(f"关键词: {KEYWORD}")
        print(f"品牌: {BRAND_NAME}")
        print("=" * 60)
        print()

        start_time = time.time()

        # 阶段1: AI内容生成
        self.test_ai_content_generation()
        self.test_ai_task_creation()

        # 阶段2: 一键分发
        self.test_publish_platforms()
        self.test_quick_publish()

        # 阶段3: 效果监控
        self.test_monitoring_dashboard()
        self.test_search_rank_check()
        self.test_ai_citation_check()

        # 生成报告
        elapsed_time = time.time() - start_time
        self.generate_report(elapsed_time)

    def generate_report(self, elapsed_time):
        """生成测试报告"""
        print()
        print("=" * 60)
        print("测试报告")
        print("=" * 60)

        # 统计各阶段结果
        stage1_results = [r for r in self.results if r["step"].startswith("1.")]
        stage2_results = [r for r in self.results if r["step"].startswith("2.")]
        stage3_results = [r for r in self.results if r["step"].startswith("3.")]

        print(f"\n✅ 阶段1 - AI内容生成: {len(stage1_results)} 个测试项")
        print(f"✅ 阶段2 - 一键分发: {len(stage2_results)} 个测试项")
        print(f"✅ 阶段3 - 效果监控: {len(stage3_results)} 个测试项")

        print(f"\n⏱️  总耗时: {elapsed_time:.2f} 秒")
        print(f"📝 总日志数: {len(self.results)} 条")

        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)

        # 保存详细报告
        report_file = f"geo_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump({
                "test_info": {
                    "website": WEBSITE,
                    "keyword": KEYWORD,
                    "brand": BRAND_NAME,
                    "test_time": datetime.now().isoformat(),
                    "elapsed_time": elapsed_time
                },
                "results": self.results
            }, f, ensure_ascii=False, indent=2)

        print(f"\n📄 详细报告已保存: {report_file}")


if __name__ == "__main__":
    tester = GEOWorkflowTester()
    tester.run_full_test()
