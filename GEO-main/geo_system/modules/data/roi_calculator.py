"""
GEO ROI计算器
计算GEO投入产出比和商业价值
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import json


@dataclass
class Investment:
    """投资项"""
    category: str
    amount: float
    description: str
    date: str


@dataclass
class Return:
    """回报项"""
    category: str
    amount: float
    description: str
    attribution_rate: float  # 归因比例（GEO贡献度）
    date: str


@dataclass
class ROIMetrics:
    """ROI指标"""
    total_investment: float
    total_return: float
    geo_attributed_return: float
    roi_ratio: float
    payback_period: float
    customer_acquisition_cost: float
    customer_lifetime_value: float


class ROICalculator:
    """
    GEO ROI计算器
    
    计算GEO策略的投入产出比，包括：
    - 直接ROI计算
    - 归因分析
    - 多维度价值评估
    - 预测和模拟
    """
    
    def __init__(self):
        self.investments: List[Investment] = []
        self.returns: List[Return] = []
        self.benchmarks = self._load_benchmarks()
    
    def _load_benchmarks(self) -> Dict:
        """加载行业基准数据"""
        return {
            "avg_roi": 3.5,  # 平均ROI
            "avg_payback_months": 6,  # 平均回收期
            "avg_cac_reduction": 0.25,  # 获客成本降低比例
            "avg_conversion_lift": 0.15,  # 转化率提升
            "industry_multipliers": {
                "b2b_saas": 4.2,
                "ecommerce": 3.8,
                "education": 3.2,
                "healthcare": 2.9,
                "finance": 3.5
            }
        }
    
    def add_investment(self, category: str, amount: float, 
                       description: str, date: str = None):
        """
        添加投资记录
        
        Args:
            category: 投资类别
            amount: 金额
            description: 描述
            date: 日期
        """
        if date is None:
            date = datetime.now().isoformat()
        
        self.investments.append(Investment(
            category=category,
            amount=amount,
            description=description,
            date=date
        ))
    
    def add_return(self, category: str, amount: float,
                   description: str, attribution_rate: float = 1.0,
                   date: str = None):
        """
        添加回报记录
        
        Args:
            category: 回报类别
            amount: 金额
            description: 描述
            attribution_rate: GEO归因比例
            date: 日期
        """
        if date is None:
            date = datetime.now().isoformat()
        
        self.returns.append(Return(
            category=category,
            amount=amount,
            description=description,
            attribution_rate=attribution_rate,
            date=date
        ))
    
    def calculate_roi(self, period_months: int = 12) -> ROIMetrics:
        """
        计算ROI
        
        Args:
            period_months: 计算周期（月）
            
        Returns:
            ROI指标
        """
        # 计算总投资
        total_investment = sum(inv.amount for inv in self.investments)
        
        # 计算总回报
        total_return = sum(ret.amount for ret in self.returns)
        
        # 计算GEO归因回报
        geo_attributed_return = sum(
            ret.amount * ret.attribution_rate for ret in self.returns
        )
        
        # 计算ROI比率
        roi_ratio = (geo_attributed_return - total_investment) / total_investment \
                    if total_investment > 0 else 0
        
        # 计算回收期
        monthly_return = geo_attributed_return / period_months
        payback_period = total_investment / monthly_return if monthly_return > 0 else float('inf')
        
        # 计算获客成本（简化版）
        customer_acquisition_cost = self._calculate_cac()
        
        # 计算客户终身价值（简化版）
        customer_lifetime_value = self._calculate_clv()
        
        return ROIMetrics(
            total_investment=total_investment,
            total_return=total_return,
            geo_attributed_return=geo_attributed_return,
            roi_ratio=roi_ratio,
            payback_period=payback_period,
            customer_acquisition_cost=customer_acquisition_cost,
            customer_lifetime_value=customer_lifetime_value
        )
    
    def _calculate_cac(self) -> float:
        """计算获客成本"""
        # 简化计算：总投资 / 新客户数
        # 实际应用中需要接入真实的客户数据
        marketing_investment = sum(
            inv.amount for inv in self.investments
            if inv.category in ["content", "promotion", "tools"]
        )
        
        # 假设每1000元投资获得10个客户
        estimated_customers = marketing_investment / 100
        
        return marketing_investment / max(estimated_customers, 1)
    
    def _calculate_clv(self) -> float:
        """计算客户终身价值"""
        # 简化计算：平均订单价值 * 购买频率 * 客户生命周期
        avg_order_value = 1000  # 假设平均订单1000元
        purchase_frequency = 2  # 每年购买2次
        customer_lifespan = 3   # 客户生命周期3年
        
        return avg_order_value * purchase_frequency * customer_lifespan
    
    def get_investment_breakdown(self) -> Dict:
        """
        获取投资明细
        
        Returns:
            按类别分类的投资明细
        """
        breakdown = {}
        for inv in self.investments:
            if inv.category not in breakdown:
                breakdown[inv.category] = {
                    "total": 0,
                    "items": []
                }
            breakdown[inv.category]["total"] += inv.amount
            breakdown[inv.category]["items"].append({
                "amount": inv.amount,
                "description": inv.description,
                "date": inv.date
            })
        
        return breakdown
    
    def get_return_breakdown(self) -> Dict:
        """
        获取回报明细
        
        Returns:
            按类别分类的回报明细
        """
        breakdown = {}
        for ret in self.returns:
            if ret.category not in breakdown:
                breakdown[ret.category] = {
                    "total": 0,
                    "geo_attributed": 0,
                    "items": []
                }
            breakdown[ret.category]["total"] += ret.amount
            breakdown[ret.category]["geo_attributed"] += ret.amount * ret.attribution_rate
            breakdown[ret.category]["items"].append({
                "amount": ret.amount,
                "geo_attributed": ret.amount * ret.attribution_rate,
                "description": ret.description,
                "date": ret.date
            })
        
        return breakdown
    
    def calculate_monthly_trend(self) -> List[Dict]:
        """
        计算月度趋势
        
        Returns:
            月度ROI趋势数据
        """
        # 按月份聚合数据
        monthly_data = {}
        
        for inv in self.investments:
            month = inv.date[:7]  # YYYY-MM
            if month not in monthly_data:
                monthly_data[month] = {"investment": 0, "return": 0}
            monthly_data[month]["investment"] += inv.amount
        
        for ret in self.returns:
            month = ret.date[:7]
            if month not in monthly_data:
                monthly_data[month] = {"investment": 0, "return": 0}
            monthly_data[month]["return"] += ret.amount * ret.attribution_rate
        
        # 转换为列表并排序
        trend = []
        for month in sorted(monthly_data.keys()):
            data = monthly_data[month]
            roi = (data["return"] - data["investment"]) / data["investment"] \
                  if data["investment"] > 0 else 0
            trend.append({
                "month": month,
                "investment": data["investment"],
                "return": data["return"],
                "roi": roi
            })
        
        return trend
    
    def compare_with_benchmarks(self, industry: str = None) -> Dict:
        """
        与行业基准对比
        
        Args:
            industry: 行业类型
            
        Returns:
            对比结果
        """
        metrics = self.calculate_roi()
        
        comparison = {
            "your_roi": metrics.roi_ratio,
            "industry_avg_roi": self.benchmarks["avg_roi"],
            "your_payback_months": metrics.payback_period,
            "industry_avg_payback": self.benchmarks["avg_payback_months"],
            "performance_vs_avg": "above" if metrics.roi_ratio > self.benchmarks["avg_roi"] else "below",
            "roi_difference": metrics.roi_ratio - self.benchmarks["avg_roi"]
        }
        
        # 行业特定对比
        if industry and industry in self.benchmarks["industry_multipliers"]:
            industry_avg = self.benchmarks["industry_multipliers"][industry]
            comparison["industry_specific_avg"] = industry_avg
            comparison["vs_industry"] = "above" if metrics.roi_ratio > industry_avg else "below"
        
        return comparison
    
    def forecast_roi(self, months: int = 12, 
                     monthly_investment: float = None,
                     growth_rate: float = 0.05) -> List[Dict]:
        """
        预测未来ROI
        
        Args:
            months: 预测月数
            monthly_investment: 月投资额
            growth_rate: 月增长率
            
        Returns:
            预测数据
        """
        if monthly_investment is None:
            # 使用历史平均投资
            if self.investments:
                monthly_investment = sum(inv.amount for inv in self.investments) / \
                                    max(len(self.investments), 1)
            else:
                monthly_investment = 5000  # 默认值
        
        forecast = []
        cumulative_investment = sum(inv.amount for inv in self.investments)
        cumulative_return = sum(ret.amount * ret.attribution_rate for ret in self.returns)
        
        current_month = datetime.now()
        
        for i in range(1, months + 1):
            # 预测月份
            forecast_month = current_month + timedelta(days=30 * i)
            
            # 预测投资（可能有增长）
            predicted_investment = monthly_investment * (1 + growth_rate) ** (i // 3)
            cumulative_investment += predicted_investment
            
            # 预测回报（滞后效应）
            # 假设投资回报有1-3个月的滞后
            if i <= 3:
                predicted_return = predicted_investment * 0.5  # 初期回报较低
            else:
                predicted_return = predicted_investment * 2.5 * (1 + growth_rate) ** i
            
            cumulative_return += predicted_return
            
            forecast.append({
                "month": forecast_month.strftime("%Y-%m"),
                "predicted_investment": round(predicted_investment, 2),
                "predicted_return": round(predicted_return, 2),
                "cumulative_investment": round(cumulative_investment, 2),
                "cumulative_return": round(cumulative_return, 2),
                "predicted_roi": round((cumulative_return - cumulative_investment) / cumulative_investment, 2),
                "payback_achieved": cumulative_return >= cumulative_investment
            })
        
        return forecast
    
    def generate_roi_report(self, industry: str = None) -> Dict:
        """
        生成ROI报告
        
        Args:
            industry: 行业类型
            
        Returns:
            完整ROI报告
        """
        metrics = self.calculate_roi()
        investment_breakdown = self.get_investment_breakdown()
        return_breakdown = self.get_return_breakdown()
        monthly_trend = self.calculate_monthly_trend()
        benchmark_comparison = self.compare_with_benchmarks(industry)
        forecast = self.forecast_roi()
        
        return {
            "report_generated": datetime.now().isoformat(),
            "summary": {
                "total_investment": metrics.total_investment,
                "total_return": metrics.total_return,
                "geo_attributed_return": metrics.geo_attributed_return,
                "roi_ratio": round(metrics.roi_ratio, 2),
                "roi_percentage": f"{metrics.roi_ratio * 100:.1f}%",
                "payback_period_months": round(metrics.payback_period, 1),
                "customer_acquisition_cost": round(metrics.customer_acquisition_cost, 2),
                "customer_lifetime_value": round(metrics.customer_lifetime_value, 2),
                "ltv_cac_ratio": round(metrics.customer_lifetime_value / max(metrics.customer_acquisition_cost, 1), 2)
            },
            "investment_breakdown": investment_breakdown,
            "return_breakdown": return_breakdown,
            "monthly_trend": monthly_trend,
            "benchmark_comparison": benchmark_comparison,
            "forecast": forecast[:6],  # 前6个月预测
            "recommendations": self._generate_recommendations(metrics, benchmark_comparison)
        }
    
    def _generate_recommendations(self, metrics: ROIMetrics, 
                                   comparison: Dict) -> List[Dict]:
        """生成优化建议"""
        recommendations = []
        
        # ROI相关建议
        if metrics.roi_ratio < 1:
            recommendations.append({
                "priority": "high",
                "category": "roi",
                "suggestion": "当前ROI为负，需要优化内容策略或降低投入成本",
                "action": "审查低效内容，集中资源在高转化渠道"
            })
        elif metrics.roi_ratio < self.benchmarks["avg_roi"]:
            recommendations.append({
                "priority": "medium",
                "category": "roi",
                "suggestion": "ROI低于行业平均，有提升空间",
                "action": "学习行业最佳实践，优化内容质量"
            })
        
        # 回收期建议
        if metrics.payback_period > 12:
            recommendations.append({
                "priority": "medium",
                "category": "payback",
                "suggestion": "回收期较长，考虑加速策略",
                "action": "增加高转化内容产出，优化分发渠道"
            })
        
        # CAC建议
        if metrics.customer_acquisition_cost > metrics.customer_lifetime_value * 0.3:
            recommendations.append({
                "priority": "high",
                "category": "cac",
                "suggestion": "获客成本偏高",
                "action": "优化内容漏斗，提升转化率"
            })
        
        # 通用建议
        recommendations.extend([
            {
                "priority": "low",
                "category": "optimization",
                "suggestion": "持续监测AI引用率，优化高引用内容",
                "action": "建立内容效果追踪机制"
            },
            {
                "priority": "low",
                "category": "expansion",
                "suggestion": "考虑扩展更多GEO渠道",
                "action": "评估新的AI搜索平台和内容形式"
            }
        ])
        
        return recommendations
    
    def save_data(self, filepath: str):
        """保存数据到文件"""
        data = {
            "investments": [
                {
                    "category": inv.category,
                    "amount": inv.amount,
                    "description": inv.description,
                    "date": inv.date
                }
                for inv in self.investments
            ],
            "returns": [
                {
                    "category": ret.category,
                    "amount": ret.amount,
                    "description": ret.description,
                    "attribution_rate": ret.attribution_rate,
                    "date": ret.date
                }
                for ret in self.returns
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def load_data(self, filepath: str):
        """从文件加载数据"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self.investments = [
            Investment(**item) for item in data["investments"]
        ]
        self.returns = [
            Return(**item) for item in data["returns"]
        ]


class GEOValueCalculator:
    """
    GEO价值计算器
    
    计算GEO带来的多维度价值
    """
    
    def __init__(self):
        self.value_categories = {
            "brand_visibility": {
                "name": "品牌可见性价值",
                "metrics": ["ai_citation_count", "brand_mention_count", "answer_space_coverage"]
            },
            "traffic_value": {
                "name": "流量价值",
                "metrics": ["ai_referral_traffic", "organic_traffic_lift", "direct_traffic"]
            },
            "conversion_value": {
                "name": "转化价值",
                "metrics": ["leads_generated", "conversion_rate", "revenue_attributed"]
            },
            "efficiency_value": {
                "name": "效率价值",
                "metrics": ["cac_reduction", "content_reuse_rate", "automation_savings"]
            }
        }
    
    def calculate_brand_value(self, metrics: Dict) -> Dict:
        """
        计算品牌价值
        
        Args:
            metrics: 品牌指标
            
        Returns:
            品牌价值评估
        """
        # 品牌可见性价值估算
        citation_value = metrics.get("ai_citation_count", 0) * 100  # 每次引用价值100元
        mention_value = metrics.get("brand_mention_count", 0) * 50   # 每次提及价值50元
        coverage_value = metrics.get("answer_space_coverage", 0) * 10000  # 覆盖率价值
        
        total_brand_value = citation_value + mention_value + coverage_value
        
        return {
            "citation_value": citation_value,
            "mention_value": mention_value,
            "coverage_value": coverage_value,
            "total_brand_value": total_brand_value,
            "equivalent_ad_spend": total_brand_value * 2  # 等效广告投入
        }
    
    def calculate_traffic_value(self, metrics: Dict) -> Dict:
        """
        计算流量价值
        
        Args:
            metrics: 流量指标
            
        Returns:
            流量价值评估
        """
        ai_traffic = metrics.get("ai_referral_traffic", 0)
        avg_cpc = metrics.get("avg_cpc", 5)  # 平均点击成本
        
        traffic_value = ai_traffic * avg_cpc
        
        return {
            "ai_traffic": ai_traffic,
            "traffic_value": traffic_value,
            "equivalent_ppc_spend": traffic_value,
            "traffic_quality_score": metrics.get("traffic_quality", 0.8)
        }
    
    def calculate_total_geo_value(self, metrics: Dict) -> Dict:
        """
        计算GEO总价值
        
        Args:
            metrics: 综合指标
            
        Returns:
            总价值评估
        """
        brand_value = self.calculate_brand_value(metrics)
        traffic_value = self.calculate_traffic_value(metrics)
        
        # 转化价值
        leads = metrics.get("leads_generated", 0)
        lead_value = metrics.get("lead_value", 200)
        conversion_value = leads * lead_value
        
        # 效率价值
        cac_savings = metrics.get("cac_reduction", 0) * metrics.get("new_customers", 0)
        
        total_value = (
            brand_value["total_brand_value"] +
            traffic_value["traffic_value"] +
            conversion_value +
            cac_savings
        )
        
        return {
            "brand_value": brand_value,
            "traffic_value": traffic_value,
            "conversion_value": conversion_value,
            "efficiency_value": cac_savings,
            "total_geo_value": total_value,
            "value_breakdown": {
                "brand": brand_value["total_brand_value"] / total_value if total_value > 0 else 0,
                "traffic": traffic_value["traffic_value"] / total_value if total_value > 0 else 0,
                "conversion": conversion_value / total_value if total_value > 0 else 0,
                "efficiency": cac_savings / total_value if total_value > 0 else 0
            }
        }


if __name__ == "__main__":
    # ROI计算器演示
    calculator = ROICalculator()
    
    # 添加投资记录
    calculator.add_investment("content", 15000, "内容创作和优化")
    calculator.add_investment("tools", 5000, "GEO工具订阅")
    calculator.add_investment("personnel", 30000, "人员成本")
    
    # 添加回报记录
    calculator.add_return("sales", 100000, "直接销售", 0.3)
    calculator.add_return("leads", 50000, "线索价值", 0.4)
    calculator.add_return("brand", 30000, "品牌价值", 0.8)
    
    # 计算ROI
    metrics = calculator.calculate_roi()
    print("=" * 60)
    print("GEO ROI计算结果")
    print("=" * 60)
    print(f"总投资: ¥{metrics.total_investment:,.2f}")
    print(f"总回报: ¥{metrics.total_return:,.2f}")
    print(f"GEO归因回报: ¥{metrics.geo_attributed_return:,.2f}")
    print(f"ROI: {metrics.roi_ratio:.2f} ({metrics.roi_ratio * 100:.1f}%)")
    print(f"回收期: {metrics.payback_period:.1f} 个月")
    print(f"获客成本: ¥{metrics.customer_acquisition_cost:.2f}")
    print(f"客户终身价值: ¥{metrics.customer_lifetime_value:.2f}")
    
    # 行业对比
    print("\n" + "=" * 60)
    print("行业对比")
    print("=" * 60)
    comparison = calculator.compare_with_benchmarks("b2b_saas")
    print(f"你的ROI: {comparison['your_roi']:.2f}")
    print(f"行业平均: {comparison['industry_avg_roi']:.2f}")
    print(f"表现: {'高于' if comparison['performance_vs_avg'] == 'above' else '低于'}平均")
    
    # 生成报告
    print("\n" + "=" * 60)
    print("生成完整报告...")
    print("=" * 60)
    report = calculator.generate_roi_report("b2b_saas")
    print(f"报告包含 {len(report['recommendations'])} 条优化建议")
