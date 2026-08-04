"""
品牌诊断服务
快速扫描品牌在AI平台的收录情况、识别可见度盲点、评估舆情风险
"""

import requests
import json
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass, asdict
from datetime import datetime
import sqlite3


class DiagnosisDimension(Enum):
    """诊断维度"""
    AI_VISIBILITY = "ai_visibility"        # AI可见度
    SEARCH_PRESENCE = "search_presence"    # 搜索表现
    CONTENT_QUALITY = "content_quality"    # 内容质量
    SENTIMENT = "sentiment"                # 舆情情感
    COMPETITIVE = "competitive"            # 竞争态势


class RiskLevel(Enum):
    """风险等级"""
    LOW = "low"           # 低风险
    MEDIUM = "medium"     # 中风险
    HIGH = "high"         # 高风险
    CRITICAL = "critical" # 严重


@dataclass
class DiagnosisItem:
    """诊断项"""
    dimension: str
    name: str
    score: int                    # 0-100
    status: str                   # good/warning/danger
    findings: List[str]           # 发现的问题
    recommendations: List[str]    # 改进建议
    risk_level: str               # low/medium/high/critical


@dataclass
class BrandDiagnosisReport:
    """品牌诊断报告"""
    id: int
    brand_name: str
    website: str
    industry: str
    overall_score: int            # 综合得分
    ai_visibility_score: int      # AI可见度得分
    search_score: int             # 搜索得分
    content_score: int            # 内容得分
    sentiment_score: int          # 舆情得分
    competitive_score: int        # 竞争得分
    diagnosis_items: List[DiagnosisItem]
    blind_spots: List[str]        # 可见度盲点
    risk_areas: List[str]         # 风险区域
    opportunities: List[str]      # 机会点
    action_plan: List[Dict]       # 行动计划
    created_at: datetime


class BrandDiagnosisService:
    """品牌诊断服务"""

    def __init__(self, db_path: str = "diagnosis.db"):
        self.db_path = db_path
        self.init_database()

    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 诊断报告表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS diagnosis_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_name TEXT NOT NULL,
                website TEXT,
                industry TEXT,
                overall_score INTEGER,
                ai_visibility_score INTEGER,
                search_score INTEGER,
                content_score INTEGER,
                sentiment_score INTEGER,
                competitive_score INTEGER,
                report_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 诊断历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS diagnosis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand_name TEXT NOT NULL,
                dimension TEXT,
                score INTEGER,
                findings TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def run_full_diagnosis(self, brand_name: str, website: str = None,
                          industry: str = None, keywords: List[str] = None) -> BrandDiagnosisReport:
        """运行完整品牌诊断"""

        if keywords is None:
            keywords = [f"{brand_name}怎么样", f"{brand_name}好不好", f"{brand_name}推荐"]

        # 执行各维度诊断
        ai_visibility = self._diagnose_ai_visibility(brand_name, keywords)
        search_presence = self._diagnose_search_presence(brand_name, website, keywords)
        content_quality = self._diagnose_content_quality(brand_name, website)
        sentiment = self._diagnose_sentiment(brand_name, keywords)
        competitive = self._diagnose_competitive(brand_name, industry)

        # 计算综合得分
        scores = [
            ai_visibility.score,
            search_presence.score,
            content_quality.score,
            sentiment.score,
            competitive.score
        ]
        overall_score = sum(scores) // len(scores)

        # 识别盲点
        blind_spots = self._identify_blind_spots(ai_visibility, search_presence)

        # 识别风险
        risk_areas = self._identify_risks(sentiment, competitive)

        # 发现机会
        opportunities = self._identify_opportunities(ai_visibility, competitive)

        # 生成行动计划
        action_plan = self._generate_action_plan(
            ai_visibility, search_presence, content_quality, sentiment, competitive
        )

        # 创建报告
        report = BrandDiagnosisReport(
            id=None,
            brand_name=brand_name,
            website=website,
            industry=industry,
            overall_score=overall_score,
            ai_visibility_score=ai_visibility.score,
            search_score=search_presence.score,
            content_score=content_quality.score,
            sentiment_score=sentiment.score,
            competitive_score=competitive.score,
            diagnosis_items=[ai_visibility, search_presence, content_quality, sentiment, competitive],
            blind_spots=blind_spots,
            risk_areas=risk_areas,
            opportunities=opportunities,
            action_plan=action_plan,
            created_at=datetime.now()
        )

        # 保存报告
        self._save_report(report)

        return report

    def _diagnose_ai_visibility(self, brand_name: str, keywords: List[str]) -> DiagnosisItem:
        """诊断AI可见度"""
        findings = []
        recommendations = []

        # 模拟检查各AI平台
        platforms = ["豆包", "DeepSeek", "Kimi", "通义千问"]
        mentioned_count = 0

        for platform in platforms:
            # 这里应该实际调用AI平台API检查
            # 模拟数据
            if platform in ["豆包", "DeepSeek"]:
                mentioned_count += 1
                findings.append(f"✅ {platform}: 已收录品牌信息")
            else:
                findings.append(f"⚠️ {platform}: 品牌提及较少")

        mention_rate = (mentioned_count / len(platforms)) * 100

        if mention_rate >= 75:
            score = 80 + (mention_rate - 75) // 5
            status = "good"
            risk = RiskLevel.LOW
        elif mention_rate >= 50:
            score = 60 + (mention_rate - 50) // 2
            status = "warning"
            risk = RiskLevel.MEDIUM
            recommendations.append("增加在Kimi和通义千问平台的内容投放")
        else:
            score = mention_rate
            status = "danger"
            risk = RiskLevel.HIGH
            recommendations.append(" urgently需要加强AI平台内容建设")
            recommendations.append("创建更多GEO优化内容")

        score = min(100, max(0, score))

        return DiagnosisItem(
            dimension=DiagnosisDimension.AI_VISIBILITY.value,
            name="AI可见度",
            score=int(score),
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value
        )

    def _diagnose_search_presence(self, brand_name: str, website: str,
                                  keywords: List[str]) -> DiagnosisItem:
        """诊断搜索表现"""
        findings = []
        recommendations = []

        # 模拟搜索结果分析
        search_engines = ["百度", "搜狗", "360搜索"]
        avg_rank = 0

        for engine in search_engines:
            # 模拟排名数据
            rank = 5  # 模拟平均排名
            avg_rank += rank
            if rank <= 3:
                findings.append(f"✅ {engine}: 排名靠前(第{rank}位)")
            elif rank <= 10:
                findings.append(f"⚠️ {engine}: 排名中等(第{rank}位)")
            else:
                findings.append(f"❌ {engine}: 排名靠后(第{rank}位)")

        avg_rank /= len(search_engines)

        if avg_rank <= 3:
            score = 90
            status = "good"
            risk = RiskLevel.LOW
        elif avg_rank <= 8:
            score = 70
            status = "warning"
            risk = RiskLevel.MEDIUM
            recommendations.append("优化SEO，提升核心关键词排名")
        else:
            score = 50
            status = "danger"
            risk = RiskLevel.HIGH
            recommendations.append(" urgently需要SEO优化")
            recommendations.append("增加高质量外链建设")

        return DiagnosisItem(
            dimension=DiagnosisDimension.SEARCH_PRESENCE.value,
            name="搜索表现",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value
        )

    def _diagnose_content_quality(self, brand_name: str, website: str) -> DiagnosisItem:
        """诊断内容质量"""
        findings = []
        recommendations = []

        # 模拟内容质量检查
        content_metrics = {
            "total_articles": 15,
            "avg_length": 1800,
            "schema_markup": False,
            "faq_count": 5,
            "freshness": "3个月前更新"
        }

        findings.append(f"📄 现有内容: {content_metrics['total_articles']} 篇文章")
        findings.append(f"✍️ 平均字数: {content_metrics['avg_length']} 字")

        if content_metrics['avg_length'] >= 1500:
            score = 70
        else:
            score = 50
            recommendations.append("增加文章深度，建议每篇1500字以上")

        if not content_metrics['schema_markup']:
            findings.append("❌ 缺少Schema结构化标记")
            recommendations.append("添加Schema.org结构化数据")
            score -= 10
        else:
            findings.append("✅ 已配置Schema标记")

        if content_metrics['faq_count'] < 10:
            findings.append(f"⚠️ FAQ数量较少({content_metrics['faq_count']}个)")
            recommendations.append("扩充FAQ内容至20个以上")
            score -= 10

        if "3个月" in content_metrics['freshness']:
            findings.append("⚠️ 内容更新不够及时")
            recommendations.append("建立内容更新机制，保持每周更新")
            score -= 10

        score = max(0, min(100, score))

        status = "good" if score >= 70 else "warning" if score >= 50 else "danger"
        risk = RiskLevel.LOW if score >= 70 else RiskLevel.MEDIUM if score >= 50 else RiskLevel.HIGH

        return DiagnosisItem(
            dimension=DiagnosisDimension.CONTENT_QUALITY.value,
            name="内容质量",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value
        )

    def _diagnose_sentiment(self, brand_name: str, keywords: List[str]) -> DiagnosisItem:
        """诊断舆情情感"""
        findings = []
        recommendations = []

        # 模拟舆情分析
        sentiment_data = {
            "positive": 65,
            "neutral": 25,
            "negative": 10
        }

        findings.append(f"😊 正面评价: {sentiment_data['positive']}%")
        findings.append(f"😐 中性评价: {sentiment_data['neutral']}%")
        findings.append(f"😟 负面评价: {sentiment_data['negative']}%")

        score = sentiment_data['positive'] + sentiment_data['neutral'] * 0.5

        if sentiment_data['negative'] > 20:
            status = "danger"
            risk = RiskLevel.HIGH
            recommendations.append(" urgently需要舆情危机处理")
            findings.append("❌ 负面舆情占比较高，需关注")
        elif sentiment_data['negative'] > 10:
            status = "warning"
            risk = RiskLevel.MEDIUM
            recommendations.append("监控负面评价，及时回应")
        else:
            status = "good"
            risk = RiskLevel.LOW
            findings.append("✅ 品牌舆情整体健康")

        return DiagnosisItem(
            dimension=DiagnosisDimension.SENTIMENT.value,
            name="舆情情感",
            score=int(score),
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value
        )

    def _diagnose_competitive(self, brand_name: str, industry: str) -> DiagnosisItem:
        """诊断竞争态势"""
        findings = []
        recommendations = []

        # 模拟竞品分析
        competitors = ["欧派", "索菲亚", "尚品宅配"]

        findings.append(f"🏆 主要竞品: {', '.join(competitors)}")

        # 模拟市场份额
        market_share = 8  # 假设市场份额8%
        findings.append(f"📊 预估市场份额: {market_share}%")

        if market_share >= 15:
            score = 85
            status = "good"
            risk = RiskLevel.LOW
            findings.append("✅ 市场地位稳固")
        elif market_share >= 8:
            score = 65
            status = "warning"
            risk = RiskLevel.MEDIUM
            findings.append("⚠️ 市场份额有待提升")
            recommendations.append("加强差异化定位")
            recommendations.append("增加品牌曝光度")
        else:
            score = 40
            status = "danger"
            risk = RiskLevel.HIGH
            findings.append("❌ 市场份额较低")
            recommendations.append(" urgently需要市场突破策略")
            recommendations.append("考虑价格战或差异化竞争")

        return DiagnosisItem(
            dimension=DiagnosisDimension.COMPETITIVE.value,
            name="竞争态势",
            score=score,
            status=status,
            findings=findings,
            recommendations=recommendations,
            risk_level=risk.value
        )

    def _identify_blind_spots(self, ai_visibility: DiagnosisItem,
                              search_presence: DiagnosisItem) -> List[str]:
        """识别可见度盲点"""
        blind_spots = []

        if ai_visibility.score < 70:
            blind_spots.append("AI平台覆盖不足，豆包、DeepSeek等平台缺乏品牌内容")
            blind_spots.append("GEO优化内容缺失，AI难以引用品牌信息")

        if search_presence.score < 70:
            blind_spots.append("长尾关键词覆盖不足")
            blind_spots.append("本地搜索优化缺失")

        return blind_spots

    def _identify_risks(self, sentiment: DiagnosisItem,
                       competitive: DiagnosisItem) -> List[str]:
        """识别风险区域"""
        risks = []

        if sentiment.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            risks.append("负面舆情风险：存在较多负面评价")

        if competitive.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            risks.append("竞争风险：市场份额较低，面临被边缘化风险")

        return risks

    def _identify_opportunities(self, ai_visibility: DiagnosisItem,
                               competitive: DiagnosisItem) -> List[str]:
        """发现机会点"""
        opportunities = []

        if ai_visibility.score < 60:
            opportunities.append("AI搜索红利期：抢先布局GEO优化，建立AI推荐优势")
            opportunities.append("内容空白领域：竞品在AI平台内容较少，有超车机会")

        if competitive.score < 70:
            opportunities.append("差异化定位：避开头部竞品正面竞争")
            opportunities.append("细分市场：专注特定人群或场景")

        return opportunities

    def _generate_action_plan(self, ai_visibility: DiagnosisItem,
                             search_presence: DiagnosisItem,
                             content_quality: DiagnosisItem,
                             sentiment: DiagnosisItem,
                             competitive: DiagnosisItem) -> List[Dict]:
        """生成行动计划"""
        actions = []

        # 紧急行动
        if sentiment.risk_level == RiskLevel.HIGH:
            actions.append({
                "priority": "urgent",
                "action": "舆情危机处理",
                "description": "回应负面评价，发布正面内容",
                "timeline": "1周内"
            })

        # 高优先级
        if ai_visibility.score < 70:
            actions.append({
                "priority": "high",
                "action": "GEO内容建设",
                "description": "创建20篇GEO优化文章和FAQ",
                "timeline": "2周内"
            })

        if content_quality.score < 70:
            actions.append({
                "priority": "high",
                "action": "内容质量提升",
                "description": "添加Schema标记，扩充FAQ，优化现有内容",
                "timeline": "3周内"
            })

        # 中优先级
        if search_presence.score < 70:
            actions.append({
                "priority": "medium",
                "action": "SEO优化",
                "description": "关键词优化，外链建设",
                "timeline": "1个月内"
            })

        # 长期行动
        actions.append({
            "priority": "low",
            "action": "持续监测",
            "description": "建立品牌监测体系，定期诊断",
            "timeline": "持续进行"
        })

        return actions

    def _save_report(self, report: BrandDiagnosisReport):
        """保存诊断报告"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        report_data = json.dumps({
            "diagnosis_items": [asdict(item) for item in report.diagnosis_items],
            "blind_spots": report.blind_spots,
            "risk_areas": report.risk_areas,
            "opportunities": report.opportunities,
            "action_plan": report.action_plan
        }, ensure_ascii=False)

        cursor.execute('''
            INSERT INTO diagnosis_reports
            (brand_name, website, industry, overall_score,
             ai_visibility_score, search_score, content_score,
             sentiment_score, competitive_score, report_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            report.brand_name, report.website, report.industry,
            report.overall_score, report.ai_visibility_score,
            report.search_score, report.content_score,
            report.sentiment_score, report.competitive_score,
            report_data
        ))

        conn.commit()
        conn.close()

    def get_report_history(self, brand_name: str, limit: int = 10) -> List[Dict]:
        """获取诊断历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM diagnosis_reports
            WHERE brand_name = ?
            ORDER BY created_at DESC
            LIMIT ?
        ''', (brand_name, limit))

        columns = [description[0] for description in cursor.description]
        reports = []

        for row in cursor.fetchall():
            report_dict = dict(zip(columns, row))
            if report_dict.get('report_data'):
                report_dict['report_data'] = json.loads(report_dict['report_data'])
            reports.append(report_dict)

        conn.close()
        return reports

    def get_score_trend(self, brand_name: str, days: int = 30) -> List[Dict]:
        """获取得分趋势"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT created_at, overall_score, ai_visibility_score
            FROM diagnosis_reports
            WHERE brand_name = ?
            AND created_at >= datetime('now', '-{} days')
            ORDER BY created_at ASC
        '''.format(days), (brand_name,))

        trends = []
        for row in cursor.fetchall():
            trends.append({
                "date": row[0],
                "overall": row[1],
                "ai_visibility": row[2]
            })

        conn.close()
        return trends


# 全局服务实例
brand_diagnosis_service = BrandDiagnosisService()


if __name__ == "__main__":
    # 测试
    service = BrandDiagnosisService()
    report = service.run_full_diagnosis(
        brand_name="织然家具",
        website="www.zhiranrome.com",
        industry="家居定制",
        keywords=["织然家具怎么样", "织然家具好不好", "全屋定制推荐"]
    )

    print("=" * 60)
    print(f"品牌诊断报告: {report.brand_name}")
    print("=" * 60)
    print(f"\n综合得分: {report.overall_score}/100")
    print(f"AI可见度: {report.ai_visibility_score}/100")
    print(f"搜索表现: {report.search_score}/100")
    print(f"内容质量: {report.content_score}/100")
    print(f"舆情情感: {report.sentiment_score}/100")
    print(f"竞争态势: {report.competitive_score}/100")

    print("\n" + "=" * 60)
    print("可见度盲点:")
    for spot in report.blind_spots:
        print(f"  ⚠️ {spot}")

    print("\n风险区域:")
    for risk in report.risk_areas:
        print(f"  🚨 {risk}")

    print("\n机会点:")
    for opp in report.opportunities:
        print(f"  💡 {opp}")

    print("\n行动计划:")
    for action in report.action_plan[:3]:
        print(f"  [{action['priority'].upper()}] {action['action']} - {action['timeline']}")
