# -*- coding: utf-8 -*-
"""
细粒度 RBAC 权限服务(阶段三 P2-6)

设计:
1. sys_permission / sys_role_permission 两表持久化权限与角色映射
2. admin 角色直接通过所有权限(代码层短路,无需查表)
3. operator/viewer 通过 sys_role_permission 表查询是否有对应权限码
4. 启动时 seed 默认权限数据(约 20 个常见权限覆盖各业务模块)

对应 PRD: 细粒度 RBAC,operator/viewer 差异化接口权限,前端菜单按权限过滤。
"""

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============ 默认权限定义(约 20 个,覆盖各业务模块) ============
# 每项: (permission_code, permission_name, module, description)
DEFAULT_PERMISSIONS: List[Tuple[str, str, str, str]] = [
    # publisher 模块
    ("publisher:multi-publish", "多平台发布", "publisher", "多平台批量发布内容"),
    ("publisher:view", "发布记录查看", "publisher", "查看发布历史与状态"),
    ("publisher:config", "发布账号配置", "publisher", "管理多平台发布账号"),
    # interactor 模块
    ("interactor:execute", "互动任务执行", "interactor", "执行点赞/评论等互动任务"),
    ("interactor:view", "互动记录查看", "interactor", "查看互动历史与统计"),
    ("interactor:config", "互动量配置", "interactor", "管理互动量配置与话术库"),
    # moderation 模块
    ("moderation:review", "人工复核", "moderation", "对自动审核结果进行人工复核"),
    ("moderation:view", "审核日志查看", "moderation", "查看内容审核日志与统计"),
    ("moderation:config", "审核规则配置", "moderation", "配置内容审核策略与阈值"),
    # analytics 模块
    ("analytics:view", "数据分析查看", "analytics", "查看仪表盘与数据趋势"),
    ("analytics:export", "数据导出", "analytics", "导出数据报表 CSV"),
    # hotpoint 模块
    ("hotpoint:view", "热点中心查看", "hotpoint", "查看多平台热榜与热点详情"),
    ("hotpoint:config", "热点筛选配置", "hotpoint", "管理热点筛选规则与告警"),
    # dm 模块
    ("dm:view", "私信管理查看", "dm", "查看多平台私信列表"),
    ("dm:reply", "私信回复", "dm", "回复用户私信"),
    # scheduling 模块
    ("scheduling:manage", "发布调度管理", "scheduling", "管理定时发布任务"),
    ("scheduling:view", "调度日历查看", "scheduling", "查看发布日历与高峰时段"),
    # risk-control 模块
    ("risk-control:view", "风控查看", "risk-control", "查看账号健康度与配额"),
    ("risk-control:config", "风控配置", "risk-control", "配置频次硬限制与代理池"),
    # comment-monitor 模块（评论监控）
    ("comment-monitor:view", "评论监控查看", "comment-monitor", "查看监控任务与抓取记录"),
    ("comment-monitor:manage", "评论监控管理", "comment-monitor", "创建/启停/编辑监控任务"),
    # local-life 模块（本地生活）
    ("local-life:view", "本地生活查看", "local-life", "搜索商家与查看商家列表"),
    ("local-life:export", "本地生活导出", "local-life", "导出商家Excel"),
    # 系统级权限(仅 admin)
    ("system:user-manage", "用户管理", "system", "管理系统用户与角色"),
    ("system:config", "系统配置", "system", "管理系统级配置与评分规则"),
]


# ============ 角色-权限映射(admin 默认拥有全部,不在此显式列出) ============
# operator: 业务执行类(不含用户管理/系统配置)
# viewer: 只读类(view 类权限)
ROLE_PERMISSION_MAP: Dict[str, List[str]] = {
    "operator": [
        # publisher
        "publisher:multi-publish",
        "publisher:view",
        "publisher:config",
        # interactor
        "interactor:execute",
        "interactor:view",
        "interactor:config",
        # moderation
        "moderation:review",
        "moderation:view",
        # analytics
        "analytics:view",
        "analytics:export",
        # hotpoint
        "hotpoint:view",
        "hotpoint:config",
        # dm
        "dm:view",
        "dm:reply",
        # scheduling
        "scheduling:manage",
        "scheduling:view",
        # risk-control
        "risk-control:view",
        # comment-monitor
        "comment-monitor:view",
        "comment-monitor:manage",
        # local-life
        "local-life:view",
        "local-life:export",
    ],
    "viewer": [
        "publisher:view",
        "interactor:view",
        "moderation:view",
        "analytics:view",
        "hotpoint:view",
        "dm:view",
        "scheduling:view",
        "risk-control:view",
        # comment-monitor / local-life 只读
        "comment-monitor:view",
        "local-life:view",
    ],
}


class PermissionService:
    """权限服务(异步 PostgreSQL)"""

    _ensured = False  # DDL 仅首次执行一次,避免每次请求都跑 CREATE TABLE/INDEX

    def __init__(self):
        self._table_ready = False
        # 内存缓存: permission_code -> permission_id; role -> set(permission_code)
        self._perm_code_to_id: Dict[str, int] = {}
        self._role_perms: Dict[str, Set[str]] = {}
        self._cache_loaded = False

    @staticmethod
    def _get_engine():
        """获取异步数据库引擎（公共方法，消除重复导入）"""
        from database.db_session import get_async_engine
        import config
        return get_async_engine(config.SAVE_DATA_OPTION)

    async def ensure_table(self) -> None:
        """创建权限表(若不存在)"""
        if PermissionService._ensured:
            return
        if self._table_ready:
            return
        try:
            from sqlalchemy import text as sql_text

            engine = self._get_engine()
            if engine is None:
                return
            async with engine.begin() as conn:
                # sys_permission 表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS sys_permission ("
                        "  permission_id SERIAL PRIMARY KEY,"
                        "  permission_code VARCHAR(64) UNIQUE NOT NULL,"
                        "  permission_name VARCHAR(128) NOT NULL DEFAULT '',"
                        "  module VARCHAR(32) NOT NULL DEFAULT '',"
                        "  description TEXT DEFAULT '',"
                        "  created_at TIMESTAMPTZ DEFAULT NOW()"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_sys_permission_module "
                        "ON sys_permission(module)"
                    )
                )
                # sys_role_permission 表
                await conn.execute(
                    sql_text(
                        "CREATE TABLE IF NOT EXISTS sys_role_permission ("
                        "  id SERIAL PRIMARY KEY,"
                        "  role VARCHAR(32) NOT NULL,"
                        "  permission_id INTEGER NOT NULL "
                        "    REFERENCES sys_permission(permission_id) ON DELETE CASCADE,"
                        "  UNIQUE(role, permission_id)"
                        ")"
                    )
                )
                await conn.execute(
                    sql_text(
                        "CREATE INDEX IF NOT EXISTS idx_sys_role_permission_role "
                        "ON sys_role_permission(role)"
                    )
                )
            self._table_ready = True
            PermissionService._ensured = True
            logger.info("[PermissionService] sys_permission / sys_role_permission 表已就绪")
        except Exception as e:
            logger.warning(f"[PermissionService] ensure_table failed: {e}")

    async def seed_default_permissions(self) -> None:
        """写入默认权限与角色映射(幂等)"""
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return
            async with engine.begin() as conn:
                # 1. 插入权限定义(ON CONFLICT 跳过)
                for code, name, module, desc in DEFAULT_PERMISSIONS:
                    await conn.execute(
                        sql_text(
                            "INSERT INTO sys_permission (permission_code, permission_name, module, description) "
                            "VALUES (:c, :n, :m, :d) "
                            "ON CONFLICT (permission_code) DO NOTHING"
                        ),
                        {"c": code, "n": name, "m": module, "d": desc},
                    )
                # 2. 构建 code -> id 映射
                rows = await conn.execute(
                    sql_text("SELECT permission_code, permission_id FROM sys_permission")
                )
                code_to_id: Dict[str, int] = {r[0]: r[1] for r in rows.fetchall()}
                # 3. 写入角色-权限映射(ON CONFLICT 跳过)
                for role, codes in ROLE_PERMISSION_MAP.items():
                    for code in codes:
                        pid = code_to_id.get(code)
                        if pid is None:
                            continue
                        await conn.execute(
                            sql_text(
                                "INSERT INTO sys_role_permission (role, permission_id) "
                                "VALUES (:r, :p) "
                                "ON CONFLICT (role, permission_id) DO NOTHING"
                            ),
                            {"r": role, "p": pid},
                        )
            # 重置缓存,下次查询时重新加载
            self._cache_loaded = False
            logger.info(
                f"[PermissionService] 默认权限已 seed: {len(DEFAULT_PERMISSIONS)} 个权限,"
                f"角色映射: admin=全部, operator={len(ROLE_PERMISSION_MAP['operator'])} 个,"
                f"viewer={len(ROLE_PERMISSION_MAP['viewer'])} 个"
            )
        except Exception as e:
            logger.warning(f"[PermissionService] seed_default_permissions failed: {e}")

    async def _load_cache(self) -> None:
        """加载权限映射到内存缓存"""
        if self._cache_loaded:
            return
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return
            async with engine.connect() as conn:
                # permission_code -> id
                rows = await conn.execute(
                    sql_text("SELECT permission_code, permission_id FROM sys_permission")
                )
                self._perm_code_to_id = {r[0]: r[1] for r in rows.fetchall()}
                # role -> set(permission_code)
                rows = await conn.execute(
                    sql_text(
                        "SELECT rp.role, p.permission_code "
                        "FROM sys_role_permission rp "
                        "JOIN sys_permission p ON rp.permission_id = p.permission_id"
                    )
                )
                self._role_perms = {}
                for r in rows.fetchall():
                    self._role_perms.setdefault(r[0], set()).add(r[1])
            self._cache_loaded = True
        except Exception as e:
            logger.warning(f"[PermissionService] _load_cache failed: {e}")

    async def has_permission(self, user: Dict[str, Any], permission_code: str) -> bool:
        """判断用户是否拥有指定权限码

        admin 角色直接返回 True(拥有所有权限)。
        其他角色查 sys_role_permission 表判断。
        """
        if not user:
            return False
        role = user.get("role") or "viewer"
        # admin 短路: 拥有所有权限
        if role == "admin":
            return True
        await self._load_cache()
        perms = self._role_perms.get(role, set())
        return permission_code in perms

    async def list_user_permissions(self, user: Dict[str, Any]) -> List[str]:
        """列出用户拥有的所有权限码

        admin 返回全部权限码;其他角色返回对应映射。
        """
        if not user:
            return []
        role = user.get("role") or "viewer"
        await self._load_cache()
        if role == "admin":
            # admin 拥有所有权限
            return sorted(self._perm_code_to_id.keys())
        perms = self._role_perms.get(role, set())
        return sorted(perms)

    async def list_all_permissions(self) -> List[Dict[str, Any]]:
        """列出所有权限定义(含模块分组)"""
        await self._load_cache()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return []
            async with engine.connect() as conn:
                rows = await conn.execute(
                    sql_text(
                        "SELECT permission_id, permission_code, permission_name, module, description, created_at "
                        "FROM sys_permission ORDER BY module, permission_code"
                    )
                )
                return [
                    {
                        "permission_id": r[0],
                        "permission_code": r[1],
                        "permission_name": r[2],
                        "module": r[3],
                        "description": r[4],
                        "created_at": str(r[5]) if r[5] else None,
                    }
                    for r in rows.fetchall()
                ]
        except Exception as e:
            logger.warning(f"[PermissionService] list_all_permissions failed: {e}")
            return []

    async def list_role_permission_map(self) -> Dict[str, List[str]]:
        """列出角色-权限映射(供前端管理界面)

        Returns:
            {"admin": ["..."], "operator": ["..."], "viewer": ["..."]}
            admin 固定为 "*" 通配,表示全部权限。
        """
        await self._load_cache()
        result: Dict[str, List[str]] = {
            "admin": ["*"],  # admin 拥有所有权限,用通配符表示
        }
        for role in ("operator", "viewer"):
            perms = self._role_perms.get(role, set())
            result[role] = sorted(perms)
        return result

    async def set_role_permissions(self, role: str, permission_codes: List[str]) -> bool:
        """设置角色权限(全量覆盖,仅 admin 可调用)

        Args:
            role: operator / viewer (admin 不可改)
            permission_codes: 权限码列表
        """
        if role == "admin":
            return False  # admin 默认拥有全部,不可显式设置
        await self.ensure_table()
        try:
            from database.db_session import get_async_engine
            import config
            from sqlalchemy import text as sql_text

            engine = get_async_engine(config.SAVE_DATA_OPTION)
            if engine is None:
                return False
            async with engine.begin() as conn:
                # 删除旧映射
                await conn.execute(
                    sql_text("DELETE FROM sys_role_permission WHERE role = :r"),
                    {"r": role},
                )
                # 插入新映射
                for code in permission_codes:
                    pid = self._perm_code_to_id.get(code)
                    if pid is None:
                        # 可能缓存未刷新,实时查询
                        row = await conn.execute(
                            sql_text(
                                "SELECT permission_id FROM sys_permission WHERE permission_code = :c"
                            ),
                            {"c": code},
                        )
                        r = row.fetchone()
                        if r is None:
                            continue
                        pid = r[0]
                        self._perm_code_to_id[code] = pid
                    await conn.execute(
                        sql_text(
                            "INSERT INTO sys_role_permission (role, permission_id) "
                            "VALUES (:r, :p) "
                            "ON CONFLICT (role, permission_id) DO NOTHING"
                        ),
                        {"r": role, "p": pid},
                    )
            # 重置缓存
            self._cache_loaded = False
            return True
        except Exception as e:
            logger.warning(f"[PermissionService] set_role_permissions failed: {e}")
            return False


# ============ 单例 ============
_service: Optional[PermissionService] = None


def get_permission_service() -> PermissionService:
    global _service
    if _service is None:
        _service = PermissionService()
    return _service
