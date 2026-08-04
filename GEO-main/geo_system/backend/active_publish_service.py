"""
主动发布服务
编排 AI 内容生成 + 图片生成 + 多平台发布，全部使用 PostgreSQL 存储
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from postgresql_database import db as postgres_db
from ai_service import ai_service
from image_generation_service import image_service
from publish_service import publish_service, PublishTask, PublishStatus, PlatformType

logger = logging.getLogger(__name__)


class ActiveTaskStatus(Enum):
    """主动发布任务状态"""
    PENDING = "pending"            # 已创建，待执行
    GENERATING = "generating"      # 正在生成内容
    GENERATING_IMAGES = "generating_images"  # 正在生成图片
    PUBLISHING = "publishing"      # 正在发布
    SUCCESS = "success"            # 全部成功
    PARTIAL = "partial"            # 部分成功
    FAILED = "failed"              # 全部失败
    CANCELLED = "cancelled"        # 已取消


@dataclass
class ActivePublishTask:
    """主动发布任务"""
    id: int = None
    user_id: int = None
    topic: str = ""                                   # 主题
    title: str = ""                                   # 最终标题
    content: str = ""                                 # 生成的内容
    keywords: List[str] = field(default_factory=list)
    brand_name: str = ""
    industry: str = ""
    domain: str = ""
    target_platforms: List[str] = field(default_factory=list)
    word_count: int = 1500
    images: List[str] = field(default_factory=list)   # 生成的图片(base64或路径)
    status: str = ActiveTaskStatus.PENDING.value
    publish_task_id: Optional[int] = None             # 关联的 publish_tasks.id
    platform_results: Dict = field(default_factory=dict)
    error_message: str = ""
    created_at: datetime = None
    updated_at: datetime = None
    completed_at: datetime = None


class ActivePublishService:
    """主动发布服务 - 一站式：生成内容→生成图片→多平台发布"""

    def __init__(self):
        self._init_db()

    def _init_db(self):
        """初始化 PostgreSQL 表"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS active_publish_tasks (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        topic TEXT NOT NULL,
                        title TEXT DEFAULT '',
                        content TEXT DEFAULT '',
                        keywords TEXT,
                        brand_name VARCHAR(255) DEFAULT '',
                        industry VARCHAR(255) DEFAULT '',
                        domain VARCHAR(255) DEFAULT '',
                        target_platforms TEXT,
                        word_count INTEGER DEFAULT 1500,
                        images TEXT,
                        status VARCHAR(30) DEFAULT 'pending',
                        publish_task_id INTEGER,
                        platform_results TEXT,
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_publish_user_id ON active_publish_tasks(user_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_publish_status ON active_publish_tasks(status)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_active_publish_created_at ON active_publish_tasks(created_at)')
                conn.commit()
                logger.info("[ActivePublish] PostgreSQL 表初始化完成")
        except Exception as e:
            logger.error(f"[ActivePublish] 数据库初始化失败: {e}")

    # ========== CRUD ==========

    def create_task(self, task: ActivePublishTask) -> Optional[ActivePublishTask]:
        """创建主动发布任务"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO active_publish_tasks
                    (user_id, topic, title, content, keywords, brand_name, industry,
                     domain, target_platforms, word_count, images, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                ''', (
                    task.user_id,
                    task.topic,
                    task.title,
                    task.content,
                    json.dumps(task.keywords, ensure_ascii=False),
                    task.brand_name,
                    task.industry,
                    task.domain,
                    json.dumps(task.target_platforms, ensure_ascii=False),
                    task.word_count,
                    json.dumps(task.images, ensure_ascii=False) if task.images else None,
                    task.status,
                    datetime.now(),
                    datetime.now()
                ))
                task.id = cursor.fetchone()[0]
                logger.info(f"[ActivePublish] 创建任务成功 id={task.id} topic={task.topic}")
                return task
        except Exception as e:
            logger.error(f"[ActivePublish] 创建任务失败: {e}")
            return None

    def get_task(self, task_id: int) -> Optional[ActivePublishTask]:
        """获取任务详情"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM active_publish_tasks WHERE id = %s', (task_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_task(row)
        except Exception as e:
            logger.error(f"[ActivePublish] 获取任务失败: {e}")
        return None

    def get_user_tasks(self, user_id: int, status: str = None, limit: int = 50) -> List[ActivePublishTask]:
        """获取用户任务列表"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                if status:
                    cursor.execute(
                        'SELECT * FROM active_publish_tasks WHERE user_id = %s AND status = %s ORDER BY created_at DESC LIMIT %s',
                        (user_id, status, limit)
                    )
                else:
                    cursor.execute(
                        'SELECT * FROM active_publish_tasks WHERE user_id = %s ORDER BY created_at DESC LIMIT %s',
                        (user_id, limit)
                    )
                rows = cursor.fetchall()
                return [self._row_to_task(row) for row in rows]
        except Exception as e:
            logger.error(f"[ActivePublish] 获取任务列表失败: {e}")
            return []

    def update_task(self, task_id: int, updates: Dict) -> Optional[ActivePublishTask]:
        """更新任务字段"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                # 白名单字段
                field_map = {
                    'title': 'title',
                    'content': 'content',
                    'keywords': 'keywords',
                    'images': 'images',
                    'status': 'status',
                    'publish_task_id': 'publish_task_id',
                    'platform_results': 'platform_results',
                    'error_message': 'error_message',
                    'completed_at': 'completed_at',
                }
                set_clauses = []
                params = []
                for k, v in updates.items():
                    if k not in field_map:
                        continue
                    col = field_map[k]
                    if k in ('keywords', 'images', 'platform_results'):
                        params.append(json.dumps(v, ensure_ascii=False) if v is not None else None)
                    elif k == 'completed_at':
                        params.append(v)
                    else:
                        params.append(v)
                    set_clauses.append(f"{col} = %s")

                if not set_clauses:
                    return self.get_task(task_id)

                set_clauses.append("updated_at = CURRENT_TIMESTAMP")
                params.append(task_id)
                cursor.execute(
                    f"UPDATE active_publish_tasks SET {', '.join(set_clauses)} WHERE id = %s",
                    params
                )
                return self.get_task(task_id)
        except Exception as e:
            logger.error(f"[ActivePublish] 更新任务失败: {e}")
            return None

    def cancel_task(self, task_id: int) -> Optional[ActivePublishTask]:
        """取消任务（仅未完成的可取消）"""
        task = self.get_task(task_id)
        if not task:
            return None
        terminal = {ActiveTaskStatus.SUCCESS.value, ActiveTaskStatus.FAILED.value,
                    ActiveTaskStatus.CANCELLED.value, ActiveTaskStatus.PARTIAL.value}
        if task.status in terminal:
            return task
        return self.update_task(task_id, {
            'status': ActiveTaskStatus.CANCELLED.value,
            'completed_at': datetime.now()
        })

    def _row_to_task(self, row) -> ActivePublishTask:
        return ActivePublishTask(
            id=row[0],
            user_id=row[1],
            topic=row[2],
            title=row[3] or "",
            content=row[4] or "",
            keywords=json.loads(row[5]) if row[5] else [],
            brand_name=row[6] or "",
            industry=row[7] or "",
            domain=row[8] or "",
            target_platforms=json.loads(row[9]) if row[9] else [],
            word_count=row[10] or 1500,
            images=json.loads(row[11]) if row[11] else [],
            status=row[12],
            publish_task_id=row[13],
            platform_results=json.loads(row[14]) if row[14] else {},
            error_message=row[15] or "",
            created_at=row[16],
            updated_at=row[17],
            completed_at=row[18]
        )

    # ========== 核心执行流程 ==========

    def execute_task(self, task_id: int) -> Dict:
        """
        执行主动发布任务，串行：生成内容 → 生成图片 → 多平台发布
        """
        task = self.get_task(task_id)
        if not task:
            return {'success': False, 'error': '任务不存在'}

        # 状态机校验
        terminal = {ActiveTaskStatus.SUCCESS.value, ActiveTaskStatus.FAILED.value,
                    ActiveTaskStatus.CANCELLED.value, ActiveTaskStatus.PARTIAL.value}
        if task.status in terminal:
            return {'success': False, 'error': f'任务已结束（{task.status}），无法重复执行'}

        try:
            # 1. 生成内容
            self.update_task(task_id, {'status': ActiveTaskStatus.GENERATING.value})
            generated = self._generate_content(task)
            if not generated.get('success'):
                self.update_task(task_id, {
                    'status': ActiveTaskStatus.FAILED.value,
                    'error_message': generated.get('error', '内容生成失败'),
                    'completed_at': datetime.now()
                })
                return generated

            title = generated['title']
            content = generated['content']
            keywords = generated.get('keywords', task.keywords)
            self.update_task(task_id, {
                'title': title,
                'content': content,
                'keywords': keywords
            })
            task.title = title
            task.content = content
            task.keywords = keywords

            # 2. 生成配图（小红书等平台必需；官网博客也可使用）
            images = []
            if self._needs_images(task.target_platforms):
                self.update_task(task_id, {'status': ActiveTaskStatus.GENERATING_IMAGES.value})
                images = self._generate_images(task)
                if images:
                    self.update_task(task_id, {'images': images})
                    task.images = images
                else:
                    logger.warning(f"[ActivePublish] 任务 {task_id} 图片生成失败，继续无图发布")

            # 3. 多平台发布
            self.update_task(task_id, {'status': ActiveTaskStatus.PUBLISHING.value})
            publish_result = self._publish_to_platforms(task, images)

            # 4. 汇总状态
            results = publish_result.get('results', {})
            has_success = any(r.get('success', False) for r in results.values())
            all_success = publish_result.get('success', False) and has_success

            final_status = (ActiveTaskStatus.SUCCESS.value if all_success
                            else ActiveTaskStatus.PARTIAL.value if has_success
                            else ActiveTaskStatus.FAILED.value)

            self.update_task(task_id, {
                'status': final_status,
                'platform_results': results,
                'publish_task_id': publish_result.get('publish_task_id'),
                'error_message': '' if has_success else publish_result.get('error', '所有平台发布失败'),
                'completed_at': datetime.now()
            })

            return {
                'success': has_success,
                'status': final_status,
                'title': title,
                'content': content,
                'keywords': keywords,
                'images': images,
                'publish_result': publish_result,
                'message': '主动发布完成' if has_success else '发布失败'
            }

        except Exception as e:
            logger.exception(f"[ActivePublish] 执行任务异常 task_id={task_id}")
            self.update_task(task_id, {
                'status': ActiveTaskStatus.FAILED.value,
                'error_message': str(e),
                'completed_at': datetime.now()
            })
            return {'success': False, 'error': f'执行异常: {e}'}

    # ========== 内容生成 ==========

    def _generate_content(self, task: ActivePublishTask) -> Dict:
        """使用 AI 生成文章内容"""
        try:
            brand_info = {
                'name': task.brand_name or '织然家具',
                'industry': task.industry or '定制家具',
                'expertise': task.keywords
            }
            result = ai_service.generate_geo_article(
                title=task.topic,
                brand_info=brand_info,
                keywords=task.keywords,
                target_platform='chatgpt',
                word_count=task.word_count
            )
            if not result.get('success'):
                return {'success': False, 'error': result.get('error', 'AI生成失败')}

            content = result.get('content', '').strip()
            if not content:
                return {'success': False, 'error': 'AI返回内容为空'}

            # 从生成内容中提取首个标题作为最终标题
            title = task.topic
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('# '):
                    title = line.lstrip('# ').strip() or title
                    break
                if line and not line.startswith('#'):
                    title = line[:40]
                    break

            logger.info(f"[ActivePublish] 内容生成成功 title={title} 长度={len(content)}")
            return {
                'success': True,
                'title': title,
                'content': content,
                'keywords': task.keywords
            }
        except Exception as e:
            logger.error(f"[ActivePublish] 内容生成异常: {e}")
            return {'success': False, 'error': str(e)}

    # ========== 图片生成 ==========

    def _needs_images(self, platforms: List[str]) -> bool:
        """判断目标平台是否需要图片"""
        if not platforms:
            return False
        image_required = {'xiaohongshu', 'douyin', 'weibo'}
        return any(p in image_required for p in platforms)

    def _generate_images(self, task: ActivePublishTask) -> List[str]:
        """根据内容生成配图（使用 image_service）"""
        try:
            images = image_service.generate_xiaohongshu_images(
                title=task.title or task.topic,
                content=task.content,
                keywords=task.keywords,
                count=3
            )
            if images:
                logger.info(f"[ActivePublish] 生成 {len(images)} 张配图")
            return images or []
        except Exception as e:
            logger.error(f"[ActivePublish] 图片生成异常: {e}")
            return []

    # ========== 多平台发布 ==========

    def _publish_to_platforms(self, task: ActivePublishTask, images: List[str]) -> Dict:
        """创建并执行 publish_tasks 任务"""
        try:
            platforms = task.target_platforms or ['website_blog']
            publish_task = PublishTask(
                content_id=task.id,
                content_type='article',
                title=task.title,
                content=task.content,
                keywords=task.keywords,
                user_id=task.user_id,
                images=images if images else None,
                target_platforms=[PlatformType(p) for p in platforms],
                status=PublishStatus.PENDING
            )
            publish_task_id = publish_service.create_publish_task(publish_task)
            if not publish_task_id:
                return {'success': False, 'error': '创建发布任务失败', 'results': {}}

            result = publish_service.execute_publish_task(
                publish_task_id, task.user_id, images=images if images else None
            )
            result['publish_task_id'] = publish_task_id
            return result
        except Exception as e:
            logger.exception(f"[ActivePublish] 发布异常")
            return {'success': False, 'error': str(e), 'results': {}}

    # ========== 统计 ==========

    def get_stats(self, user_id: int) -> Dict:
        """获取用户主动发布统计"""
        try:
            with postgres_db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT status, COUNT(*) FROM active_publish_tasks WHERE user_id = %s GROUP BY status',
                    (user_id,)
                )
                status_dist = {row[0]: row[1] for row in cursor.fetchall()}
                cursor.execute(
                    'SELECT COUNT(*) FROM active_publish_tasks WHERE user_id = %s',
                    (user_id,)
                )
                total = cursor.fetchone()[0]
                return {
                    'total': total,
                    'status_distribution': status_dist,
                    'success_count': status_dist.get(ActiveTaskStatus.SUCCESS.value, 0) + status_dist.get(ActiveTaskStatus.PARTIAL.value, 0)
                }
        except Exception as e:
            logger.error(f"[ActivePublish] 获取统计失败: {e}")
            return {'total': 0, 'status_distribution': {}, 'success_count': 0}


# 全局实例
active_publish_service = ActivePublishService()
