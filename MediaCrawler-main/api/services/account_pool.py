# -*- coding: utf-8 -*-
"""多账号池管理：Cookie + IP 组合的健康度管理

核心能力：
1. 多Cookie存储：支持数据库存储多个Cookie
2. 健康度评分：100分制，成功+5，失败-5~-50
3. 自动切换：检测到风控/验证码 → 立即切换Cookie+IP组合
4. 自动恢复：冷却到期的账号自动恢复为healthy
5. 坏IP标记：被风控的IP自动标记跳过
"""
import os
import time
import uuid
import random
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent


# ============================================================
# 数据库模型（延迟导入，避免循环依赖）
# ============================================================
_DB_MODELS_READY = False

def _ensure_db_model():
    """确保数据库模型已注册"""
    global _DB_MODELS_READY
    if _DB_MODELS_READY:
        return
    try:
        from sqlalchemy import Column, Integer, Text, String, BigInteger
        from database.models import Base
        # 检查是否已定义
        existing_tables = set(Base.metadata.tables.keys())
        if 'account_pool' not in existing_tables:
            class AccountPoolModel(Base):
                """账号池表 - 多Cookie多IP管理"""
                __tablename__ = 'account_pool'
                id = Column(Integer, primary_key=True, comment='主键ID')
                account_id = Column(String(64), unique=True, index=True, comment='账号唯一ID')
                platform = Column(String(20), default='dy', index=True, comment='平台: dy/xhs/bili')
                cookie = Column(Text, default='', comment='Cookie字符串')
                cookie_alias = Column(String(100), default='', comment='Cookie别名(备注)')
                proxy_ip = Column(String(50), default='', comment='绑定的代理IP')
                proxy_port = Column(Integer, default=0, comment='代理端口')
                proxy_user = Column(String(100), default='', comment='代理用户名')
                proxy_password = Column(String(200), default='', comment='代理密码')
                status = Column(String(20), default='healthy', comment='状态: healthy/cooldown/banned/dead')
                health_score = Column(Integer, default=100, comment='健康度评分(0-100)')
                fail_count = Column(Integer, default=0, comment='连续失败次数')
                success_count = Column(Integer, default=0, comment='连续成功次数')
                total_requests = Column(Integer, default=0, comment='总请求数')
                total_fails = Column(Integer, default=0, comment='总失败数')
                cooldown_until = Column(BigInteger, default=0, comment='冷却到期时间戳(秒)')
                cooldown_reason = Column(String(100), default='', comment='冷却原因')
                last_used_at = Column(BigInteger, default=0, comment='最后使用时间戳(秒)')
                created_at = Column(BigInteger, comment='创建时间戳(秒)')
                updated_at = Column(BigInteger, comment='更新时间戳(秒)')
                owner_user_id = Column(String(64), index=True, default='', comment='归属用户ID(数据隔离)')

            # 注册到全局，供外部引用
            globals()['AccountPoolModel'] = AccountPoolModel
        _DB_MODELS_READY = True
    except Exception as e:
        logger.warning(f"[AccountPool] DB model setup skipped: {e}")
        _DB_MODELS_READY = True  # 避免重复尝试


_ensure_db_model()


# ============================================================
# 失败类型 → 响应策略
# ============================================================
FAIL_TYPE_POLICY = {
    # fail_type: (health_delta, account_cooldown_seconds, should_switch)
    # account_cooldown_seconds: 仅在账号确实需要冷却时使用（连续失败或健康分过低）
    # 风控类失败通常只切换IP，不冷却Cookie账号（IP被风控，Cookie可能仍可用）
    "captcha":        (-15, 300,  True),   # 验证码：-15分，账号冷却5分钟(仅连续失败时)，立即切换
    "blocked":        (-20, 600,  True),   # 被封(status 2483)：-20分，账号冷却10分钟(仅连续失败时)，立即切换
    "verify_check":   (-10, 300,  True),   # 搜索拦截：-10分，账号冷却5分钟(仅连续失败时)，立即切换
    "cookie_invalid": (-50, 0,    True),   # Cookie失效：-50分，标记dead
    "timeout":        (-5,  0,    False),  # 超时：-5分，不切换（连续3次才切换）
    "rate_limit":     (-15, 180,  True),   # 频率限制：-15分，账号冷却3分钟(仅连续失败时)，立即切换
    "network_error":  (-5,  0,    False),  # 网络错误：-5分，不切换
}


@dataclass
class Account:
    """账号数据类（内存中操作，定期同步到数据库）"""
    account_id: str
    platform: str = "dy"
    cookie: str = ""
    cookie_alias: str = ""
    proxy_ip: str = ""
    proxy_port: int = 0
    proxy_user: str = ""
    proxy_password: str = ""
    network_interface: str = ""  # 网卡名: eth0/eth1/eth2（用于多IP出站）
    public_ip: str = ""          # 绑定的公网IP（监控展示用）
    status: str = "healthy"          # healthy / cooldown / banned / dead
    health_score: int = 100
    fail_count: int = 0
    success_count: int = 0
    total_requests: int = 0
    total_fails: int = 0
    cooldown_until: float = 0.0
    cooldown_reason: str = ""
    last_used_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    owner_user_id: str = ""


# ============================================================
# 多网卡IP映射（服务器多公网IP配置）
# ============================================================
# 默认网卡到公网IP的映射（启动时自动探测）
_NETWORK_INTERFACE_MAP: Dict[str, str] = {}

async def _detect_network_interfaces():
    """探测服务器上可用的网卡和对应的公网IP（并行探测，避免卡住）"""
    global _NETWORK_INTERFACE_MAP
    if _NETWORK_INTERFACE_MAP:
        return _NETWORK_INTERFACE_MAP

    import subprocess
    import concurrent.futures

    # 检测常见网卡名
    candidate_interfaces = ["eth0", "eth1", "eth2", "eth3", "ens3", "ens4", "ens5"]
    available = []

    # 获取所有UP状态的网卡
    try:
        result = subprocess.run(
            ["ip", "-o", "link", "show", "up"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                iface = parts[1].rstrip(":").lower()
                if iface in candidate_interfaces:
                    available.append(iface)
    except Exception as e:
        logger.warning(f"[AccountPool] Failed to list interfaces: {e}")
        available = ["eth0"]

    logger.info(f"[AccountPool] Detecting public IPs for interfaces: {available}")

    def _probe_iface(iface: str) -> tuple:
        """探测单个网卡的公网IP（在线程池中并行执行）"""
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", "4", "--interface", iface, "ifconfig.me"],
                capture_output=True, text=True, timeout=5
            )
            ip = result.stdout.strip()
            if ip and ip.count(".") == 3 and len(ip) <= 15:
                return (iface, ip)
        except Exception:
            pass
        return (iface, None)

    # 并行探测所有网卡（避免单个网卡超时卡住整个流程）
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(available)) as executor:
            futures = {executor.submit(_probe_iface, iface): iface for iface in available}
            for future in concurrent.futures.as_completed(futures, timeout=15):
                iface, ip = future.result()
                if ip:
                    _NETWORK_INTERFACE_MAP[iface] = ip
                    logger.info(f"[AccountPool] Detected {iface} → public IP: {ip}")
    except concurrent.futures.TimeoutExpired:
        logger.warning(f"[AccountPool] Some interface probes timed out, continuing with partial results")
    except Exception as e:
        logger.warning(f"[AccountPool] Error during interface detection: {e}")

    if not _NETWORK_INTERFACE_MAP:
        _NETWORK_INTERFACE_MAP["eth0"] = "default"
        logger.warning(f"[AccountPool] No interfaces detected, using default eth0")

    logger.info(f"[AccountPool] Network interface map: {_NETWORK_INTERFACE_MAP}")
    return _NETWORK_INTERFACE_MAP


def get_available_interfaces() -> Dict[str, str]:
    """获取可用网卡到公网IP的映射"""
    return _NETWORK_INTERFACE_MAP.copy()


async def _check_ip_health_for_platform(iface: str, platform: str = "dy") -> bool:
    """检测某个网卡的 IP 是否被目标平台风控

    通过访问平台首页，检查返回内容是否为空壳页（被风控的标志）
    返回 True 表示 IP 健康（未被风控）
    """
    import httpx
    platform_urls = {
        "dy": "https://www.douyin.com",
        "douyin": "https://www.douyin.com",
        "xhs": "https://www.xiaohongshu.com",
        "bili": "https://www.bilibili.com",
    }
    check_url = platform_urls.get(platform, "https://www.douyin.com")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        from tools.httpx_util import make_async_client
        async with make_async_client(network_interface=iface, timeout=10) as client:
            r = await client.get(check_url, headers=headers, follow_redirects=True)
            # 空壳页通常 < 5000 字符，正常页面 > 20000 字符
            is_healthy = len(r.text) > 10000
            if not is_healthy:
                logger.warning(f"[AccountPool] IP health check: {iface} returned {len(r.text)} bytes (likely blocked by {platform})")
            return is_healthy
    except Exception as e:
        logger.warning(f"[AccountPool] IP health check failed for {iface}: {e}")
        return True  # 检查失败时不标记为坏，避免误判


class AccountPool:
    """账号池管理器：自动健康检测、自动切换、自动恢复"""

    def __init__(self, platform: str = "dy", owner_user_id: str = ""):
        self.platform = platform
        self.owner_user_id = owner_user_id
        self.accounts: List[Account] = []
        self.current_account: Optional[Account] = None
        self._lock = asyncio.Lock()
        self._bad_ips: Dict[str, float] = {}  # 被标记为坏的IP → 标记时间戳
        self._bad_ip_ttl = 600  # 坏IP标记有效期 10 分钟（避免被风控的IP被快速重试）
        self._db_session_factory = None

    def set_db_session_factory(self, factory):
        """设置数据库session工厂"""
        self._db_session_factory = factory

    async def load_from_db(self):
        """从数据库加载所有账号"""
        if not self._db_session_factory:
            logger.warning("[AccountPool] No DB session factory, skip loading")
            return

        try:
            async with self._db_session_factory() as session:
                from sqlalchemy import select
                from database.models import Base
                # 获取模型类
                model_cls = globals().get('AccountPoolModel')
                if not model_cls:
                    _ensure_db_model()
                    model_cls = globals().get('AccountPoolModel')
                if not model_cls:
                    return

                stmt = select(model_cls).where(
                    model_cls.platform == self.platform
                )
                if self.owner_user_id:
                    stmt = stmt.where(model_cls.owner_user_id == self.owner_user_id)

                result = await session.execute(stmt)
                rows = result.scalars().all()

                self.accounts = []
                for row in rows:
                    acc = Account(
                        account_id=row.account_id,
                        platform=row.platform,
                        cookie=row.cookie,
                        cookie_alias=row.cookie_alias,
                        proxy_ip=row.proxy_ip,
                        proxy_port=row.proxy_port,
                        proxy_user=row.proxy_user,
                        proxy_password=row.proxy_password,
                        status=row.status,
                        health_score=row.health_score,
                        fail_count=row.fail_count,
                        success_count=row.success_count,
                        total_requests=row.total_requests,
                        total_fails=row.total_fails,
                        cooldown_until=row.cooldown_until,
                        cooldown_reason=row.cooldown_reason,
                        last_used_at=row.last_used_at,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        owner_user_id=row.owner_user_id or "",
                    )
                    # 启动时检查冷却是否已到期
                    if acc.status == "cooldown" and time.time() >= acc.cooldown_until:
                        acc.status = "healthy"
                        acc.cooldown_reason = ""
                    self.accounts.append(acc)

                logger.info(f"[AccountPool] Loaded {len(self.accounts)} accounts for platform={self.platform}")
        except Exception as e:
            logger.error(f"[AccountPool] Failed to load from DB: {e}")

    async def save_to_db(self, account: Account):
        """保存单个账号到数据库"""
        if not self._db_session_factory:
            return

        try:
            async with self._db_session_factory() as session:
                from sqlalchemy import select
                model_cls = globals().get('AccountPoolModel')
                if not model_cls:
                    return

                result = await session.execute(
                    select(model_cls).where(model_cls.account_id == account.account_id)
                )
                row = result.scalar_one_or_none()

                now = int(time.time())
                account.updated_at = now

                if row:
                    row.status = account.status
                    row.health_score = account.health_score
                    row.fail_count = account.fail_count
                    row.success_count = account.success_count
                    row.total_requests = account.total_requests
                    row.total_fails = account.total_fails
                    row.cooldown_until = account.cooldown_until
                    row.cooldown_reason = account.cooldown_reason
                    row.last_used_at = account.last_used_at
                    row.cookie = account.cookie
                    row.proxy_ip = account.proxy_ip
                    row.proxy_port = account.proxy_port
                    row.updated_at = now
                else:
                    new_row = model_cls(
                        account_id=account.account_id,
                        platform=account.platform,
                        cookie=account.cookie,
                        cookie_alias=account.cookie_alias,
                        proxy_ip=account.proxy_ip,
                        proxy_port=account.proxy_port,
                        proxy_user=account.proxy_user,
                        proxy_password=account.proxy_password,
                        status=account.status,
                        health_score=account.health_score,
                        fail_count=account.fail_count,
                        success_count=account.success_count,
                        total_requests=account.total_requests,
                        total_fails=account.total_fails,
                        cooldown_until=account.cooldown_until,
                        cooldown_reason=account.cooldown_reason,
                        last_used_at=account.last_used_at,
                        created_at=now,
                        updated_at=now,
                        owner_user_id=account.owner_user_id,
                    )
                    session.add(new_row)

                await session.commit()
        except Exception as e:
            logger.error(f"[AccountPool] Failed to save account {account.account_id}: {e}")

    async def add_account(
        self,
        cookie: str,
        cookie_alias: str = "",
        proxy_ip: str = "",
        proxy_port: int = 0,
        proxy_user: str = "",
        proxy_password: str = "",
        network_interface: str = "",
        public_ip: str = "",
    ) -> Account:
        """添加新账号到池中"""
        async with self._lock:
            # 如果Cookie已存在，更新而非新增
            for acc in self.accounts:
                if acc.cookie == cookie:
                    acc.cookie_alias = cookie_alias or acc.cookie_alias
                    acc.proxy_ip = proxy_ip or acc.proxy_ip
                    acc.proxy_port = proxy_port or acc.proxy_port
                    acc.proxy_user = proxy_user or acc.proxy_user
                    acc.proxy_password = proxy_password or acc.proxy_password
                    if network_interface:
                        acc.network_interface = network_interface
                    if public_ip:
                        acc.public_ip = public_ip
                    if acc.status == "dead":
                        acc.status = "healthy"
                        acc.health_score = 100
                        acc.fail_count = 0
                    await self.save_to_db(acc)
                    logger.info(f"[AccountPool] Updated existing account {acc.account_id}")
                    return acc

            account = Account(
                account_id=f"acc_{uuid.uuid4().hex[:12]}",
                platform=self.platform,
                cookie=cookie,
                cookie_alias=cookie_alias or f"账号{len(self.accounts)+1}",
                proxy_ip=proxy_ip,
                proxy_port=proxy_port,
                proxy_user=proxy_user,
                proxy_password=proxy_password,
                network_interface=network_interface,
                public_ip=public_ip,
                owner_user_id=self.owner_user_id,
            )
            self.accounts.append(account)
            await self.save_to_db(account)
            logger.info(f"[AccountPool] Added new account {account.account_id} ({account.cookie_alias})")
            return account

    async def remove_account(self, account_id: str) -> bool:
        """移除账号"""
        async with self._lock:
            for i, acc in enumerate(self.accounts):
                if acc.account_id == account_id:
                    self.accounts.pop(i)
                    if self.current_account and self.current_account.account_id == account_id:
                        self.current_account = None
                    # 从数据库删除
                    if self._db_session_factory:
                        try:
                            async with self._db_session_factory() as session:
                                from sqlalchemy import select, delete
                                model_cls = globals().get('AccountPoolModel')
                                if model_cls:
                                    await session.execute(
                                        delete(model_cls).where(model_cls.account_id == account_id)
                                    )
                                    await session.commit()
                        except Exception as e:
                            logger.error(f"[AccountPool] Failed to delete from DB: {e}")
                    logger.info(f"[AccountPool] Removed account {account_id}")
                    return True
            return False

    async def get_healthy_account(self) -> Optional[Account]:
        """获取健康账号：优先用health_score最高的、最久未使用的

        每次请求动态随机分配可用网卡（IP），实现Cookie×IP的随机组合，
        而不是固定绑定。这样3 Cookie × 3 IP = 9种组合，分散风控效果更好。
        """
        async with self._lock:
            now = time.time()
            # 先恢复冷却到期的账号
            for acc in self.accounts:
                if acc.status == "cooldown" and now >= acc.cooldown_until:
                    acc.status = "healthy"
                    acc.cooldown_reason = ""
                    acc.fail_count = 0
                    logger.info(f"[AccountPool] Account {acc.account_id} recovered from cooldown")

            # 清理过期的坏IP标记
            self._cleanup_expired_bad_ips()

            # 筛选健康账号（跳过坏代理IP）
            healthy = [
                a for a in self.accounts
                if a.status == "healthy"
                and a.cookie
                and (not a.proxy_ip or a.proxy_ip not in self._bad_ips)
            ]

            # 如果所有账号的代理IP都被标记为坏，清除标记重试
            if not healthy and self._bad_ips:
                logger.warning(
                    f"[AccountPool] All accounts filtered by bad IPs ({len(self._bad_ips)} bad), "
                    f"clearing marks and retrying"
                )
                self.clear_bad_ips()
                healthy = [a for a in self.accounts if a.status == "healthy" and a.cookie]

            if not healthy:
                logger.warning(f"[AccountPool] No healthy accounts available! "
                             f"Total={len(self.accounts)}, "
                             f"cooldown={sum(1 for a in self.accounts if a.status=='cooldown')}, "
                             f"dead={sum(1 for a in self.accounts if a.status=='dead')}")
                return None

            # 按 health_score 降序，再按 last_used_at 升序（最久未使用的优先）
            healthy.sort(key=lambda a: (-a.health_score, a.last_used_at))

            selected = healthy[0]
            selected.last_used_at = now
            selected.total_requests += 1

            # 动态分配网卡（随机选一个可用IP，避免与上次相同）
            selected.network_interface, selected.public_ip = self._pick_random_interface(selected)

            self.current_account = selected

            # 打印当前请求使用的Cookie和IP（方便监控）
            cookie_preview = selected.cookie[:30] + "..." if len(selected.cookie) > 30 else selected.cookie
            logger.info(
                f"[AccountPool] >>> 选中账号: {selected.cookie_alias} | "
                f"IP: {selected.network_interface} ({selected.public_ip}) | "
                f"Cookie: {cookie_preview} | "
                f"健康分: {selected.health_score} | "
                f"总请求: {selected.total_requests}"
            )

            # 异步保存（不阻塞）
            asyncio.create_task(self.save_to_db(selected))
            return selected

    def _pick_random_interface(self, account: Account) -> tuple:
        """随机选择一个可用网卡（IP）。

        策略：
        1. 从所有网卡中过滤掉坏IP（带TTL，过期自动恢复）
        2. 优先选择与上次不同的网卡（提高IP轮换率）
        3. 随机选择，避免可预测性
        """
        if not _NETWORK_INTERFACE_MAP:
            return ("", "")

        # 先清理过期的坏IP标记
        self._cleanup_expired_bad_ips()

        # 过滤掉坏IP的网卡
        available = [
            (iface, ip) for iface, ip in _NETWORK_INTERFACE_MAP.items()
            if iface not in self._bad_ips and ip not in self._bad_ips
        ]

        if not available:
            # 所有网卡都是坏IP且未过期，只能清除标记重试
            logger.warning(f"[AccountPool] All interfaces marked bad (and not expired), clearing for random pick")
            self.clear_bad_ips()
            available = list(_NETWORK_INTERFACE_MAP.items())

        # 优先选择与上次不同的网卡
        last_iface = account.network_interface
        different = [item for item in available if item[0] != last_iface]
        pool_to_choose = different if different else available

        # 随机选择
        chosen = random.choice(pool_to_choose)
        return chosen

    async def report_success(self, account_id: str):
        """报告成功：health_score +5（上限100），重置fail_count"""
        async with self._lock:
            for acc in self.accounts:
                if acc.account_id == account_id:
                    acc.health_score = min(100, acc.health_score + 5)
                    acc.fail_count = 0
                    acc.success_count += 1
                    if acc.status == "cooldown":
                        acc.status = "healthy"
                        acc.cooldown_until = 0
                        acc.cooldown_reason = ""
                    asyncio.create_task(self.save_to_db(acc))
                    logger.info(f"[AccountPool] Account {account_id} success: "
                              f"score={acc.health_score}, streak={acc.success_count}")
                    return

    async def report_failure(self, account_id: str, fail_type: str = "network_error"):
        """报告失败：根据类型扣分/冷却/封禁"""
        async with self._lock:
            for acc in self.accounts:
                if acc.account_id == account_id:
                    acc.total_fails += 1
                    acc.fail_count += 1
                    acc.success_count = 0

                    policy = FAIL_TYPE_POLICY.get(fail_type, FAIL_TYPE_POLICY["network_error"])
                    health_delta, cooldown_sec, should_switch = policy

                    acc.health_score = max(0, acc.health_score + health_delta)

                    # 打印失败详情（包含使用的IP和Cookie）
                    cookie_preview = acc.cookie[:30] + "..." if len(acc.cookie) > 30 else acc.cookie
                    logger.warning(
                        f"[AccountPool] >>> 请求失败 | "
                        f"账号: {acc.cookie_alias} | "
                        f"IP: {acc.network_interface} ({acc.public_ip}) | "
                        f"Cookie: {cookie_preview} | "
                        f"失败类型: {fail_type} | "
                        f"扣分: {health_delta} | "
                        f"当前健康分: {acc.health_score} | "
                        f"连续失败: {acc.fail_count}"
                    )

                    # Cookie失效 → 标记dead (通知由主进程通过日志检测触发)
                    if fail_type == "cookie_invalid":
                        acc.status = "dead"
                        acc.cooldown_reason = "Cookie失效"
                        logger.warning(f"[AccountPool] Account {account_id} ({acc.cookie_alias}) marked DEAD (cookie invalid)")
                    # 健康分过低 → 冷却账号
                    elif acc.health_score < 30:
                        acc.status = "cooldown"
                        acc.cooldown_until = time.time() + max(cooldown_sec, 600)
                        acc.cooldown_reason = f"健康分过低({acc.health_score})"
                        logger.warning(f"[AccountPool] Account {account_id} ({acc.cookie_alias}) cooldown: "
                                     f"健康分过低 {acc.health_score}, 冷却 {cooldown_sec}s")
                    # 连续失败3次 → 冷却账号（避免Cookie持续被风控）
                    elif acc.fail_count >= 3:
                        acc.status = "cooldown"
                        acc.cooldown_until = time.time() + cooldown_sec
                        acc.cooldown_reason = f"连续失败{acc.fail_count}次({fail_type})"
                        logger.warning(f"[AccountPool] Account {account_id} ({acc.cookie_alias}) cooldown {cooldown_sec}s: "
                                     f"连续失败 {acc.fail_count} 次 (score: {acc.health_score})")
                    # 首次/二次失败 → 只扣分+切换IP，账号保持可用（换IP后Cookie可能仍可用）
                    else:
                        logger.info(f"[AccountPool] Account {account_id} ({acc.cookie_alias}) 保持可用 "
                                   f"(fail_count: {acc.fail_count}/3, score: {acc.health_score})，仅切换IP")

                    # 标记IP为坏IP（如果配置了IP）
                    if acc.proxy_ip and fail_type in ("captcha", "blocked", "verify_check"):
                        self._bad_ips[acc.proxy_ip] = time.time()
                        logger.info(f"[AccountPool] Marked proxy IP {acc.proxy_ip} as bad (TTL={self._bad_ip_ttl}s)")

                    # 标记网卡IP为坏IP（多公网IP场景）
                    if acc.network_interface and fail_type in ("captcha", "blocked", "verify_check"):
                        self._bad_ips[acc.network_interface] = time.time()
                        logger.info(f"[AccountPool] Marked network interface {acc.network_interface} as bad (TTL={self._bad_ip_ttl}s)")

                    asyncio.create_task(self.save_to_db(acc))
                    return should_switch

    async def switch_account(self, reason: str = "") -> Optional[Account]:
        """立即切换账号：标记当前账号冷却，取出下一个健康账号

        动态随机分配网卡（IP），避免与失败的IP相同
        """
        async with self._lock:
            if self.current_account:
                old_id = self.current_account.account_id
                old_iface = self.current_account.network_interface
                logger.info(f"[AccountPool] Switching from account {old_id} (reason: {reason}, last iface: {old_iface})")
                # 不在这里改状态，report_failure已经处理了

            # 获取下一个健康账号
            now = time.time()
            # 恢复冷却到期的
            for acc in self.accounts:
                if acc.status == "cooldown" and now >= acc.cooldown_until:
                    acc.status = "healthy"
                    acc.cooldown_reason = ""

            healthy = [a for a in self.accounts
                       if a.status == "healthy" and a.cookie
                       and (not self.current_account or a.account_id != self.current_account.account_id)
                       and (not a.proxy_ip or a.proxy_ip not in self._bad_ips)]
            if not healthy:
                # 没有其他账号，尝试用当前账号（但降低优先级）
                all_healthy = [a for a in self.accounts
                               if a.status == "healthy" and a.cookie
                               and (not a.proxy_ip or a.proxy_ip not in self._bad_ips)]
                if all_healthy:
                    healthy = all_healthy
                else:
                    logger.error(f"[AccountPool] No alternative account available for switch!")
                    return None

            healthy.sort(key=lambda a: (-a.health_score, a.last_used_at))
            selected = healthy[0]
            selected.last_used_at = now
            selected.total_requests += 1

            # 动态分配网卡（随机选一个可用IP，优先与失败的不同）
            selected.network_interface, selected.public_ip = self._pick_random_interface(selected)

            self.current_account = selected
            asyncio.create_task(self.save_to_db(selected))

            # 打印切换后的账号和IP（方便监控）
            cookie_preview = selected.cookie[:30] + "..." if len(selected.cookie) > 30 else selected.cookie
            logger.info(
                f"[AccountPool] >>> 切换账号: {selected.cookie_alias} | "
                f"新IP: {selected.network_interface} ({selected.public_ip}) | "
                f"Cookie: {cookie_preview} | "
                f"健康分: {selected.health_score} | "
                f"切换原因: {reason}"
            )
            return selected

    def is_ip_bad(self, ip: str) -> bool:
        """检查IP是否被标记为坏IP（过期自动清除）"""
        self._cleanup_expired_bad_ips()
        return ip in self._bad_ips

    def clear_bad_ips(self):
        """清除坏IP标记（定期清理，给IP恢复机会）"""
        cleared = len(self._bad_ips)
        self._bad_ips.clear()
        if cleared:
            logger.info(f"[AccountPool] Cleared {cleared} bad IP marks")

    def _cleanup_expired_bad_ips(self):
        """清理过期的坏IP标记"""
        now = time.time()
        expired = [k for k, ts in self._bad_ips.items() if now - ts > self._bad_ip_ttl]
        for k in expired:
            self._bad_ips.pop(k, None)
        if expired:
            logger.info(f"[AccountPool] Expired bad IPs cleared: {expired}")

    def _check_cookie_format(self, cookie: str) -> Dict:
        """检查Cookie格式是否包含平台必需的登录态字段（快速检查，不发网络请求）

        Returns:
            {valid: bool, missing_fields: list, check_field: str}
        """
        if not cookie:
            return {"valid": False, "missing_fields": ["Cookie为空"], "check_field": ""}

        # 各平台必需的登录态字段
        required_fields_map = {
            "dy": ["sessionid", "sessionid_ss", "uid_tt"],
            "douyin": ["sessionid", "sessionid_ss", "uid_tt"],
            "xhs": ["web_session"],
            "xiaohongshu": ["web_session"],
            "wb": ["SUB"],
            "weibo": ["SUB"],
            "ks": ["passToken", "userId"],
            "kuaishou": ["passToken", "userId"],
            "bili": ["SESSDATA"],
            "bilibili": ["SESSDATA"],
            "x_twitter": ["auth_token", "ct0"],
            "x": ["auth_token", "ct0"],
        }
        required = required_fields_map.get(self.platform, [])
        missing = [f for f in required if f not in cookie]
        check_field = required[0] if required else ""
        return {"valid": len(missing) == 0, "missing_fields": missing, "check_field": check_field}

    def _get_cookie_status(self, account: Account) -> str:
        """根据账号状态和Cookie格式判断Cookie的真实状态

        Returns:
            valid / invalid / expired / cooldown / unknown
        """
        if not account.cookie:
            return "invalid"

        # 先检查格式
        fmt = self._check_cookie_format(account.cookie)
        if not fmt["valid"]:
            return "invalid"

        # 根据运行时状态判断
        if account.status == "dead":
            return "expired"  # Cookie已被标记为失效（运行时检测到登录过期）
        if account.status == "cooldown":
            return "cooldown"
        if account.status == "banned":
            return "expired"
        return "valid"

    async def check_all_health(self) -> Dict:
        """主动执行真实健康检测：检查所有Cookie格式 + 所有IP是否被block

        这是"真实展示"的核心：不只依赖被动失败记录，而是主动检测当前状态。
        - Cookie: 检查格式是否包含必需登录态字段（快速）
        - IP: 通过访问平台首页检查IP是否被风控（网络请求）

        Returns:
            {accounts_checked, ips_checked, cookie_results, ip_results, summary}
        """
        now = time.time()
        self._cleanup_expired_bad_ips()

        # 1. 检查所有Cookie格式
        cookie_results = []
        for acc in self.accounts:
            fmt = self._check_cookie_format(acc.cookie)
            cookie_status = self._get_cookie_status(acc)
            cookie_results.append({
                "account_id": acc.account_id,
                "alias": acc.cookie_alias,
                "cookie_status": cookie_status,
                "has_required_fields": fmt["valid"],
                "missing_fields": fmt["missing_fields"],
                "check_field": fmt["check_field"],
                "runtime_status": acc.status,
                "health_score": acc.health_score,
                "fail_count": acc.fail_count,
            })

        # 2. 检查所有IP健康状态（并行检测所有网卡）
        ip_results = {}
        if _NETWORK_INTERFACE_MAP:
            tasks = []
            iface_list = []
            for iface, ip in _NETWORK_INTERFACE_MAP.items():
                # 先检查是否在坏IP列表中
                is_bad = iface in self._bad_ips or ip in self._bad_ips
                if is_bad:
                    marked_time = self._bad_ips.get(iface) or self._bad_ips.get(ip, now)
                    remaining_ttl = max(0, int(self._bad_ip_ttl - (now - marked_time)))
                    ip_results[iface] = {
                        "ip": ip,
                        "status": "blocked",
                        "marked_bad": True,
                        "remaining_ttl": remaining_ttl,
                        "last_checked": int(now),
                    }
                else:
                    # 需要实际检测
                    tasks.append(_check_ip_health_for_platform(iface, self.platform))
                    iface_list.append(iface)

            # 并行检测未标记为坏IP的网卡
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for iface, result in zip(iface_list, results):
                    ip = _NETWORK_INTERFACE_MAP.get(iface, "")
                    if isinstance(result, Exception):
                        ip_results[iface] = {
                            "ip": ip,
                            "status": "unknown",
                            "marked_bad": False,
                            "error": str(result),
                            "last_checked": int(now),
                        }
                    elif result:
                        ip_results[iface] = {
                            "ip": ip,
                            "status": "healthy",
                            "marked_bad": False,
                            "last_checked": int(now),
                        }
                    else:
                        # IP被风控，主动标记为坏IP
                        self._bad_ips[iface] = now
                        ip_results[iface] = {
                            "ip": ip,
                            "status": "blocked",
                            "marked_bad": True,
                            "remaining_ttl": self._bad_ip_ttl,
                            "last_checked": int(now),
                        }
                        logger.warning(f"[AccountPool] Health check: {iface} ({ip}) is BLOCKED by {self.platform}")
        else:
            ip_results["default"] = {
                "ip": "unknown",
                "status": "unknown",
                "marked_bad": False,
                "last_checked": int(now),
            }

        # 3. 汇总
        cookie_valid = sum(1 for r in cookie_results if r["cookie_status"] == "valid")
        cookie_invalid = sum(1 for r in cookie_results if r["cookie_status"] == "invalid")
        cookie_expired = sum(1 for r in cookie_results if r["cookie_status"] == "expired")
        ip_healthy = sum(1 for r in ip_results.values() if r["status"] == "healthy")
        ip_blocked = sum(1 for r in ip_results.values() if r["status"] == "blocked")

        return {
            "platform": self.platform,
            "checked_at": int(now),
            "accounts_checked": len(cookie_results),
            "ips_checked": len(ip_results),
            "cookie_results": cookie_results,
            "ip_results": ip_results,
            "summary": {
                "cookie_valid": cookie_valid,
                "cookie_invalid": cookie_invalid,
                "cookie_expired": cookie_expired,
                "ip_healthy": ip_healthy,
                "ip_blocked": ip_blocked,
            },
        }

    def get_pool_status(self) -> Dict:
        """获取账号池状态摘要（含Cookie/IP block详情）"""
        now = time.time()
        self._cleanup_expired_bad_ips()

        healthy = [a for a in self.accounts if a.status == "healthy"]
        cooldown = [a for a in self.accounts if a.status == "cooldown"]
        dead = [a for a in self.accounts if a.status == "dead"]

        # 构建坏IP详情列表
        bad_ip_list = []
        for key, marked_time in self._bad_ips.items():
            remaining_ttl = max(0, int(self._bad_ip_ttl - (now - marked_time)))
            # 尝试找到对应的网卡名和IP
            ip_addr = _NETWORK_INTERFACE_MAP.get(key, key)
            bad_ip_list.append({
                "key": key,
                "interface": key if key in _NETWORK_INTERFACE_MAP else "",
                "ip": ip_addr,
                "marked_at": int(marked_time),
                "remaining_ttl": remaining_ttl,
            })

        # 构建每个IP的健康状态
        ip_health = {}
        for iface, ip in _NETWORK_INTERFACE_MAP.items():
            is_bad = iface in self._bad_ips or ip in self._bad_ips
            if is_bad:
                marked_time = self._bad_ips.get(iface) or self._bad_ips.get(ip, now)
                remaining_ttl = max(0, int(self._bad_ip_ttl - (now - marked_time)))
                ip_health[iface] = {
                    "ip": ip,
                    "status": "blocked",
                    "remaining_ttl": remaining_ttl,
                }
            else:
                ip_health[iface] = {
                    "ip": ip,
                    "status": "healthy",
                    "remaining_ttl": 0,
                }

        return {
            "platform": self.platform,
            "total": len(self.accounts),
            "healthy": len(healthy),
            "cooldown": len(cooldown),
            "dead": len(dead),
            "bad_ips": len(self._bad_ips),
            "bad_ip_list": bad_ip_list,
            "ip_health": ip_health,
            "current_account": self.current_account.account_id if self.current_account else None,
            "accounts": [
                {
                    "account_id": a.account_id,
                    "alias": a.cookie_alias,
                    "status": a.status,
                    "cookie_status": self._get_cookie_status(a),
                    "cookie_missing_fields": self._check_cookie_format(a.cookie)["missing_fields"],
                    "health_score": a.health_score,
                    "fail_count": a.fail_count,
                    "success_count": a.success_count,
                    "total_requests": a.total_requests,
                    "total_fails": a.total_fails,
                    "cooldown_remaining": max(0, int(a.cooldown_until - now)) if a.status == "cooldown" else 0,
                    "cooldown_reason": a.cooldown_reason,
                    "last_used_at": a.last_used_at,
                    "has_cookie": bool(a.cookie),
                    "proxy_ip": a.proxy_ip,
                    "network_interface": a.network_interface,
                    "public_ip": a.public_ip,
                    "ip_blocked": (a.network_interface in self._bad_ips) if a.network_interface else False,
                }
                for a in self.accounts
            ],
            "network_interfaces": _NETWORK_INTERFACE_MAP,
        }


# ============================================================
# 全局账号池实例管理
# ============================================================
_global_pools: Dict[str, AccountPool] = {}


def get_account_pool(platform: str = "dy", owner_user_id: str = "") -> AccountPool:
    """获取或创建全局账号池实例"""
    key = f"{platform}:{owner_user_id}"
    if key not in _global_pools:
        pool = AccountPool(platform=platform, owner_user_id=owner_user_id)
        _global_pools[key] = pool
        logger.info(f"[AccountPool] Created new pool for {key}")
    return _global_pools[key]


async def init_account_pool(platform: str = "dy", owner_user_id: str = "", db_session_factory=None) -> AccountPool:
    """初始化账号池：创建实例 + 从数据库加载 + 探测多网卡"""
    pool = get_account_pool(platform, owner_user_id)
    if db_session_factory:
        pool.set_db_session_factory(db_session_factory)
        await pool.load_from_db()

    # 探测服务器多网卡配置
    await _detect_network_interfaces()

    # 注意: 不在启动时做 IP 健康检查，因为抖音首页大小不能准确反映 IP 是否被风控
    # (首页可能返回空壳页，但搜索 API 仍可用; 反之亦然)
    # 坏IP 标记由运行时的 report_failure 自动管理（带 10 分钟 TTL）

    # 给没有绑定网卡的账号自动分配（优先分配健康IP）
    if _NETWORK_INTERFACE_MAP and pool.accounts:
        interfaces = list(_NETWORK_INTERFACE_MAP.keys())
        for i, acc in enumerate(pool.accounts):
            if not acc.network_interface:
                iface = interfaces[i % len(interfaces)]
                acc.network_interface = iface
                acc.public_ip = _NETWORK_INTERFACE_MAP[iface]
                logger.info(f"[AccountPool] Auto-assigned {acc.account_id} → {iface} ({acc.public_ip})")
                await pool.save_to_db(acc)

    return pool


# ============================================================
# 错误分类工具
# ============================================================
def classify_error(error: Exception, response_text: str = "") -> str:
    """根据异常和响应内容分类错误类型

    Args:
        error: 异常对象
        response_text: HTTP响应文本

    Returns:
        fail_type: captcha/blocked/verify_check/cookie_invalid/timeout/rate_limit/network_error
    """
    error_str = str(error).lower()
    response_lower = response_text.lower()

    # Cookie失效 / 登录过期 (需要明确标识: expire/invalid/过期/401/403)
    if any(kw in error_str for kw in ["cookie", "unauthorized", "session", "认证", "登录", "login"]):
        if "expire" in error_str or "invalid" in error_str or "过期" in error_str:
            return "cookie_invalid"
    if response_lower and ("unauthorized" in response_lower or "403" in response_lower or '"code":401' in response_lower):
        return "cookie_invalid"

    # 被封禁 / 临时限流 (status 2483, "请先登录，再继续搜索吧" 是搜索限流, 不是 Cookie 失效)
    if "2483" in error_str or "blocked" in error_str or "account blocked" in error_str:
        return "blocked"
    if any(kw in error_str for kw in ["请先登录", "请先登陆", "login required"]):
        return "blocked"

    # 验证码
    if any(kw in error_str for kw in ["captcha", "slider", "验证码", "verifycenter", "验证"]):
        return "captcha"
    if any(kw in response_lower for kw in ["captcha", "verifycenter"]):
        return "captcha"

    # 搜索拦截
    if "verify_check" in error_str or "nil_type" in error_str:
        return "verify_check"

    # 频率限制
    if any(kw in error_str for kw in ["rate limit", "频率", "频繁", "too many", "429"]):
        return "rate_limit"

    # 超时
    if any(kw in error_str for kw in ["timeout", "timed out", "超时"]):
        return "timeout"

    # 网络错误
    return "network_error"
