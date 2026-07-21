# -*- coding: utf-8 -*-
"""
X Twitter Cookie 池管理器

功能：
1. 从环境变量加载多个 cookie（X_TWITTER_COOKIES_POOL 用 | 分隔）
2. 轮询选择 cookie，降低单个账号被风控的风险
3. 跟踪每个 cookie 的健康状态（成功/失败次数）
4. 失败的 cookie 进入冷却期，避免持续使用失效 cookie
5. 提供 API 接口查看池状态、添加/删除 cookie
6. 文件持久化：运行时添加的 cookie 保存到文件，重启不丢失
"""
import json
import os
import time
import random
from typing import Any, Dict, List, Optional

# Cookie 池配置
COOLDOWN_SECONDS = 1800  # 失败后冷却 30 分钟
MAX_FAILURES = 3  # 连续失败 3 次进入冷却
HEALTH_CHECK_INTERVAL = 3600  # 健康检查间隔（仅用于状态展示）

# 持久化文件路径（运行时添加的 cookie 保存到此文件，重启后自动加载）
_PERSIST_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "cookie_pool.json",
)

# 内存中的 cookie 池状态
# 结构: { cookie_str: { "failures": int, "successes": int, "last_used": int, "cooldown_until": int, "label": str } }
_cookie_pool: Dict[str, Dict[str, Any]] = {}
_last_pool_str: str = ""


def _load_persisted_pool() -> List[str]:
    """从持久化文件加载运行时添加的 cookie"""
    try:
        if not os.path.exists(_PERSIST_FILE):
            return []
        with open(_PERSIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookies = data.get("cookies", [])
        return [c for c in cookies if c and isinstance(c, str)]
    except Exception as e:
        print(f"[cookie_pool] 加载持久化文件失败: {e}")
        return []


def _save_persisted_pool(cookies: List[str]):
    """保存运行时添加的 cookie 到持久化文件"""
    try:
        os.makedirs(os.path.dirname(_PERSIST_FILE), exist_ok=True)
        with open(_PERSIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"cookies": cookies, "saved_at": int(time.time())}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[cookie_pool] 保存持久化文件失败: {e}")


def _get_runtime_cookies() -> List[str]:
    """获取运行时通过 API 添加的 cookie（从持久化文件）"""
    return _load_persisted_pool()


def _add_runtime_cookie(cookie: str):
    """添加一个运行时 cookie 到持久化文件"""
    cookies = _load_persisted_pool()
    if cookie not in cookies:
        cookies.append(cookie)
        _save_persisted_pool(cookies)
        # 同步到环境变量（当前进程生效）
        os.environ["X_TWITTER_COOKIES_POOL"] = " | ".join(cookies)


def _remove_runtime_cookie(cookie: str):
    """从持久化文件移除一个运行时 cookie"""
    cookies = _load_persisted_pool()
    if cookie in cookies:
        cookies.remove(cookie)
        _save_persisted_pool(cookies)
        os.environ["X_TWITTER_COOKIES_POOL"] = " | ".join(cookies)


def _get_user_cookies_sync() -> List[str]:
    """获取用户级别的 cookies（同步数据库查询）"""
    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import sessionmaker
        from config.db_config import postgres_db_config

        # 创建同步引擎（独立于异步引擎）
        sync_engine = create_engine(
            f"postgresql://{postgres_db_config['user']}:{postgres_db_config['password']}@{postgres_db_config['host']}:{postgres_db_config['port']}/{postgres_db_config['db_name']}",
            pool_pre_ping=True,
        )
        Session = sessionmaker(bind=sync_engine)

        from database.user_models import UserCookieModel

        with Session() as session:
            result = session.execute(
                select(UserCookieModel)
                .where(UserCookieModel.user_id == 1)
                .where(UserCookieModel.platform == "x_twitter")
                .where(UserCookieModel.status == "active")
                .order_by(UserCookieModel.created_ts.asc())
            )
            rows = result.scalars().all()
            return [r.cookie_str for r in rows]

    except ImportError as e:
        # psycopg2 等依赖缺失,静默降级(使用环境变量 cookies 即可)
        # 只在第一次失败时打印,避免日志污染
        import os as _os
        _warn_flag = "/tmp/.cookie_pool_pg_warn"
        if not _os.path.exists(_warn_flag):
            print(f"[cookie_pool] 用户级 cookies 依赖缺失({e}),降级使用环境变量 cookies")
            try:
                open(_warn_flag, "w").write("1")
            except Exception:
                pass
        return []
    except Exception as e:
        print(f"[cookie_pool] 获取用户级 cookies 失败: {e}")
        return []


def _parse_pool_from_env() -> List[str]:
    """合并所有 cookie 来源（环境变量 + 持久化文件 + cookie_manager + 用户级 + 单 cookie）

    统一从多个来源收集 cookie，去重后返回。这样无论是通过 .env、
    运行时 API、还是现有 /api/cookies/pool 系统（数据库用户级）添加的 cookie，
    都能被 X Workbench 使用。
    """
    all_cookies: List[str] = []

    # 1. 环境变量中的 pool（.env 配置的，使用 ||| 作为分隔符，与 cookie_manager 一致）
    pool_str = os.getenv("X_TWITTER_COOKIES_POOL", "").strip()
    if pool_str:
        for c in pool_str.split("|||"):
            c = c.strip()
            if c and c not in all_cookies:
                all_cookies.append(c)

    # 2. 持久化文件中的运行时 cookie（通过 X Workbench API 添加的）
    for c in _load_persisted_pool():
        if c and c not in all_cookies:
            all_cookies.append(c)

    # 3. 从现有 cookie_manager 全局池获取（环境变量/文件）
    try:
        from api.services.cookie_manager import get_cookie_pool
        for c in get_cookie_pool("x_twitter"):
            if c and c not in all_cookies:
                all_cookies.append(c)
    except Exception as e:
        print(f"[cookie_pool] 从 cookie_manager 全局池加载失败（可忽略）: {e}")

    # 4. 从用户级 cookie 池获取（数据库）
    for c in _get_user_cookies_sync():
        if c and c not in all_cookies:
            all_cookies.append(c)

    # 5. 单 cookie 兜底
    single = os.getenv("X_TWITTER_COOKIES", "").strip()
    if single and single not in all_cookies:
        all_cookies.append(single)

    return all_cookies


def _sync_pool_state():
    """同步环境变量与内存池状态

    注意：必须把所有来源的 cookie 都纳入组合签名，
    否则当通过 cookie_manager 添加的 cookie 不会触发同步。
    """
    global _last_pool_str, _cookie_pool

    pool_str = os.getenv("X_TWITTER_COOKIES_POOL", "").strip()
    single_str = os.getenv("X_TWITTER_COOKIES", "").strip()

    # 从 cookie_manager 获取（现有系统的全局 cookies）
    manager_cookies = []
    try:
        from api.services.cookie_manager import get_cookie_pool
        manager_cookies = get_cookie_pool("x_twitter") or []
    except Exception:
        pass
    manager_str = "|".join(manager_cookies)

    # 从持久化文件获取
    file_cookies = _load_persisted_pool() or []
    file_str = "|".join(file_cookies)

    # 从用户级 cookie 池获取（数据库）
    user_cookies = _get_user_cookies_sync()
    user_cookies_str = "|".join(user_cookies)

    # 组合签名：包含所有来源，任一变化都触发同步
    combined_signature = pool_str + "||" + single_str + "||" + manager_str + "||" + file_str + "||" + user_cookies_str
    if combined_signature == _last_pool_str:
        return

    _last_pool_str = combined_signature
    cookies = _parse_pool_from_env()

    # 移除已不存在的 cookie
    existing_keys = set(_cookie_pool.keys())
    new_keys = set(cookies)
    for k in existing_keys - new_keys:
        del _cookie_pool[k]

    # 添加新 cookie（使用唯一递增编号，避免 label 重复）
    existing_max = 0
    for state in _cookie_pool.values():
        # 从 "cookie_N" 中提取数字
        try:
            n = int(state["label"].replace("cookie_", ""))
            if n > existing_max:
                existing_max = n
        except (ValueError, AttributeError):
            pass

    next_num = existing_max + 1
    for c in cookies:
        if c not in _cookie_pool:
            _cookie_pool[c] = {
                "failures": 0,
                "successes": 0,
                "last_used": 0,
                "cooldown_until": 0,
                "label": f"cookie_{next_num}",
            }
            next_num += 1


def get_cookie_from_pool() -> Optional[str]:
    """从池中选择一个可用的 cookie（轮询 + 冷却检查）"""
    _sync_pool_state()

    if not _cookie_pool:
        return None

    now = int(time.time())
    available = []
    for cookie, state in _cookie_pool.items():
        if state["cooldown_until"] > now:
            continue
        # 优先级权重: 成功次数多的优先，但也会轮询
        available.append((cookie, state))

    if not available:
        # 所有 cookie 都在冷却中，选冷却时间最早结束的
        earliest = min(_cookie_pool.items(), key=lambda x: x[1]["cooldown_until"])
        print(f"[cookie_pool] 所有 cookie 都在冷却中，使用最早可用的: {earliest[1]['label']}")
        return earliest[0]

    # 按 last_used 升序排序（最久未使用的优先），加一点随机性
    available.sort(key=lambda x: x[1]["last_used"])
    # 从前 2 个中随机选一个，增加随机性
    pick_from = available[:min(2, len(available))]
    chosen = random.choice(pick_from)
    chosen[1]["last_used"] = now
    print(f"[cookie_pool] 选中 {chosen[1]['label']}（成功 {chosen[1]['successes']} / 失败 {chosen[1]['failures']}）")
    return chosen[0]


def mark_cookie_success(cookie_str: str):
    """标记 cookie 使用成功"""
    _sync_pool_state()
    if cookie_str in _cookie_pool:
        _cookie_pool[cookie_str]["successes"] += 1
        _cookie_pool[cookie_str]["failures"] = 0  # 重置失败计数
        _cookie_pool[cookie_str]["cooldown_until"] = 0


def mark_cookie_failure(cookie_str: str, reason: str = ""):
    """标记 cookie 使用失败"""
    _sync_pool_state()
    if cookie_str not in _cookie_pool:
        return

    state = _cookie_pool[cookie_str]
    state["failures"] += 1

    if state["failures"] >= MAX_FAILURES:
        state["cooldown_until"] = int(time.time()) + COOLDOWN_SECONDS
        state["failures"] = 0  # 重置失败计数，进入冷却
        print(f"[cookie_pool] {state['label']} 连续失败 {MAX_FAILURES} 次，进入冷却 {COOLDOWN_SECONDS}s（原因: {reason}）")


def get_pool_status() -> List[Dict[str, Any]]:
    """获取 cookie 池状态"""
    _sync_pool_state()

    now = int(time.time())
    items = []
    for idx, (cookie, state) in enumerate(_cookie_pool.items(), 1):
        # 脱敏显示
        masked = cookie[:30] + "..." if len(cookie) > 30 else cookie
        in_cooldown = state["cooldown_until"] > now
        items.append({
            "index": idx,
            "label": state["label"],
            "cookie_preview": masked,
            "successes": state["successes"],
            "failures": state["failures"],
            "last_used": state["last_used"],
            "cooldown_until": state["cooldown_until"],
            "in_cooldown": in_cooldown,
            "status": "cooldown" if in_cooldown else ("healthy" if state["successes"] > 0 else "unused"),
        })
    return items


def get_pool_summary() -> Dict[str, Any]:
    """获取 cookie 池汇总信息"""
    _sync_pool_state()

    now = int(time.time())
    total = len(_cookie_pool)
    available = sum(1 for s in _cookie_pool.values() if s["cooldown_until"] <= now)
    in_cooldown = total - available

    return {
        "total": total,
        "available": available,
        "in_cooldown": in_cooldown,
        "cooldown_seconds": COOLDOWN_SECONDS,
        "max_failures": MAX_FAILURES,
    }


def add_cookie_to_env(cookie_str: str) -> bool:
    """添加 cookie 到池中（持久化到文件 + 同步到环境变量）

    持久化文件保存在 data/cookie_pool.json，重启后自动加载。
    """
    _sync_pool_state()
    cookie_str = cookie_str.strip()
    if not cookie_str:
        return False

    # 检查是否已存在（环境变量 + 持久化文件 + 单 cookie）
    existing = _parse_pool_from_env()
    if cookie_str in existing:
        return False

    # 添加到持久化文件（重启后仍可用）
    _add_runtime_cookie(cookie_str)

    # 强制重新同步内存池
    _last_pool_str = ""
    _sync_pool_state()
    print(f"[cookie_pool] 已添加 cookie 并持久化，当前池大小: {len(_cookie_pool)}")
    return True


def remove_cookie_from_env(cookie_str: str) -> bool:
    """从池中移除 cookie（同步从持久化文件和环境变量移除）

    支持两种方式：
    1. 传完整 cookie 字符串
    2. 传 label（如 "cookie_1"）—— 更安全，前端不需要完整 cookie
    """
    _sync_pool_state()

    # 方式 2：通过 label 查找完整 cookie
    if cookie_str.startswith("cookie_"):
        target_cookie = None
        for c, state in _cookie_pool.items():
            if state["label"] == cookie_str:
                target_cookie = c
                break
        if not target_cookie:
            return False
        cookie_str = target_cookie

    # 从持久化文件移除
    _remove_runtime_cookie(cookie_str)

    # 也从环境变量移除（如果有）
    pool_str = os.getenv("X_TWITTER_COOKIES_POOL", "").strip()
    if pool_str:
        cookies = [c.strip() for c in pool_str.split("|") if c.strip()]
        if cookie_str in cookies:
            cookies.remove(cookie_str)
            os.environ["X_TWITTER_COOKIES_POOL"] = " | ".join(cookies)

    # 如果是单 cookie（X_TWITTER_COOKIES），不实际清除环境变量（避免误操作）
    # 仅从内存池移除

    _last_pool_str = ""  # 强制重新同步
    _sync_pool_state()
    print(f"[cookie_pool] 已移除 cookie，当前池大小: {len(_cookie_pool)}")
    return True


def clear_all_failures():
    """清除所有 cookie 的失败计数和冷却状态"""
    _sync_pool_state()
    for state in _cookie_pool.values():
        state["failures"] = 0
        state["cooldown_until"] = 0
    print("[cookie_pool] 已清除所有失败计数和冷却状态")
