# -*- coding: utf-8 -*-
"""
报表导出服务

迁移自 GEO-main/geo_system/backend/export_service.py，适配 MediaCrawler：
1. CSV 导出（零依赖，通用）
2. Excel 导出（openpyxl，若未安装则降级 CSV）
3. 支持 Dashboard / 平台对比 / 内容表现 等报表

对应 PRD 5.5 报表导出。
"""

import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ExportService:
    """报表导出服务"""

    async def export_dashboard_csv(self, days: int = 7) -> bytes:
        """导出仪表盘报表（CSV）"""
        from .analytics_service import get_analytics_service

        data = await get_analytics_service().get_dashboard(days=days)
        output = io.StringIO()
        output.write("\ufeff")  # BOM（Excel 中文兼容）
        writer = csv.writer(output)

        writer.writerow(["MediaCrawler 运营报表", f"最近 {days} 天"])
        writer.writerow([])
        writer.writerow(["=== 汇总数据 ==="])
        summary = data.get("summary", {})
        for k, v in summary.items():
            if isinstance(v, list):
                writer.writerow([k, f"{len(v)} 个"])
            else:
                writer.writerow([k, v])

        writer.writerow([])
        writer.writerow(["=== 趋势数据 ==="])
        writer.writerow(["日期", "发布量"])
        for t in data.get("trends", []):
            writer.writerow([t.get("date"), t.get("publish_count", 0)])

        writer.writerow([])
        writer.writerow(["=== 平台分布 ==="])
        writer.writerow(["平台", "数量"])
        for p in data.get("platform_distribution", []):
            writer.writerow([p.get("platform"), p.get("count", 0)])

        writer.writerow([])
        writer.writerow([f"导出时间: {datetime.utcnow().isoformat()}"])

        content = output.getvalue()
        output.close()
        return content.encode("utf-8")

    async def export_platform_comparison_csv(self, days: int = 30) -> bytes:
        """导出平台对比报表（CSV）"""
        from .analytics_service import get_analytics_service

        data = await get_analytics_service().get_platform_comparison(days=days)
        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)

        writer.writerow(["平台对比报表", f"最近 {days} 天"])
        writer.writerow([])
        writer.writerow(["平台", "发布总量", "成功量", "成功率(%)"])
        for p in data.get("platforms", []):
            writer.writerow(
                [p["platform"], p["total"], p["success"], p["success_rate"]]
            )
        writer.writerow([])
        writer.writerow([f"导出时间: {datetime.utcnow().isoformat()}"])

        content = output.getvalue()
        output.close()
        return content.encode("utf-8")

    async def export_content_performance_csv(self, limit: int = 100) -> bytes:
        """导出内容表现报表（CSV）"""
        from .analytics_service import get_analytics_service

        data = await get_analytics_service().get_content_performance(limit=limit)
        output = io.StringIO()
        output.write("\ufeff")
        writer = csv.writer(output)

        writer.writerow(["内容表现报表"])
        writer.writerow([])
        writer.writerow(["ID", "内容预览", "Tweet ID", "发布时间"])
        for item in data.get("items", []):
            writer.writerow(
                [
                    item["id"],
                    item["content_preview"],
                    item.get("tweet_id", ""),
                    item.get("created_at", ""),
                ]
            )
        writer.writerow([])
        writer.writerow([f"导出时间: {datetime.utcnow().isoformat()}"])

        content = output.getvalue()
        output.close()
        return content.encode("utf-8")

    async def export_excel(self, report_type: str, days: int = 7) -> bytes:
        """Excel 导出（尝试 openpyxl，失败降级 CSV）

        Args:
            report_type: dashboard / platform_comparison / content_performance
        """
        try:
            from openpyxl import Workbook

            if report_type == "dashboard":
                csv_bytes = await self.export_dashboard_csv(days)
            elif report_type == "platform_comparison":
                csv_bytes = await self.export_platform_comparison_csv(days)
            else:
                csv_bytes = await self.export_content_performance_csv()

            # 简单方案：CSV 转 Excel（用 openpyxl 写入）
            wb = Workbook()
            ws = wb.active
            ws.title = report_type
            text = csv_bytes.decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text))
            for row in reader:
                ws.append(row)
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()
        except ImportError:
            logger.info("[Export] openpyxl 未安装，降级为 CSV")
            if report_type == "dashboard":
                return await self.export_dashboard_csv(days)
            elif report_type == "platform_comparison":
                return await self.export_platform_comparison_csv(days)
            else:
                return await self.export_content_performance_csv()
        except Exception as e:
            logger.error(f"[Export] Excel 导出失败: {e}")
            raise


_export: Optional[ExportService] = None


def get_export_service() -> ExportService:
    global _export
    if _export is None:
        _export = ExportService()
    return _export
