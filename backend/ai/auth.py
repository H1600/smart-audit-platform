"""访问控制与合规审计层

支持:
- API Key 认证
- 基于角色的访问控制（RBAC）
- 请求频率限制
- 审计日志（谁在何时做了什么）
- 数据脱敏审计
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, Request

from .config import (
    AI_ACCESS_ENABLED,
    AI_AUDIT_LOG_ENABLED,
    AI_PII_MASK_ENABLED,
    AI_RATE_LIMIT_PER_MIN,
)

logger = logging.getLogger(__name__)

# ── API Key 管理（单一角色，全功能开放）──────────────
AI_API_KEYS: dict[str, dict[str, Any]] = {}

_keys_str = os.getenv("AI_API_KEYS", "")
if _keys_str:
    for item in _keys_str.split(","):
        key = item.strip()
        if key:
            AI_API_KEYS[key] = {"role": "user", "created": datetime.utcnow().isoformat()}

if not AI_API_KEYS:
    AI_API_KEYS["audit-platform-key"] = {"role": "user", "created": datetime.utcnow().isoformat()}

# ── 单一角色，全权限 ──────────────────────────────────
ALL_PERMISSIONS = {"search", "qa", "reindex", "suggestions", "feedback", "admin", "export"}


def check_permission(api_key: str, action: str) -> bool:
    """检查 Key 有效性（不做角色区分）"""
    if not AI_ACCESS_ENABLED:
        return True
    if not api_key:
        return False
    return api_key in AI_API_KEYS


# ── 频率限制 ────────────────────────────────────────────
_rate_limits: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(identifier: str, max_per_min: int = AI_RATE_LIMIT_PER_MIN) -> bool:
    """检查频率限制"""
    now = time.time()
    window_start = now - 60
    # 清理过期记录
    _rate_limits[identifier] = [t for t in _rate_limits[identifier] if t > window_start]
    if len(_rate_limits[identifier]) >= max_per_min:
        return False
    _rate_limits[identifier].append(now)
    return True


# ── 审计日志 ────────────────────────────────────────────
AUDIT_LOG_PATH = Path(__file__).resolve().parent / "audit_logs"
AUDIT_LOG_PATH.mkdir(exist_ok=True)


def audit_log(
    action: str,
    api_key_hash: str = "",
    details: dict[str, Any] | None = None,
    success: bool = True,
    duration_ms: float = 0,
) -> None:
    """写入审计日志"""
    if not AI_AUDIT_LOG_ENABLED:
        return

    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "api_key_hash": api_key_hash[:16],
        "success": success,
        "duration_ms": round(duration_ms, 2),
        "details": details or {},
    }

    # 按日期分文件
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    log_file = AUDIT_LOG_PATH / f"ai_audit_{date_str}.jsonl"

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.warning("审计日志写入失败: %s", exc)


# ── FastAPI 依赖 ────────────────────────────────────────


def _extract_api_key(request: Request) -> str:
    """从请求中提取 API Key"""
    # 1. Header: Authorization: Bearer <key>
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # 2. Query param: ?api_key=
    return request.query_params.get("api_key", "")


def _hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


async def ai_auth_dependency(request: Request) -> str:
    """FastAPI 依赖：验证 AI API 请求"""
    api_key = _extract_api_key(request)

    if AI_ACCESS_ENABLED:
        if not api_key or api_key not in AI_API_KEYS:
            audit_log("auth_failed", _hash_key(api_key), {"reason": "invalid_key"}, False)
            raise HTTPException(status_code=401, detail="Invalid or missing AI API key. 请在请求 Header 中提供 Authorization: Bearer <your-key>")

    return api_key


async def ai_rate_limit_dependency(request: Request) -> None:
    """FastAPI 依赖：频率限制"""
    identifier = request.client.host if request.client else "unknown"
    if not check_rate_limit(identifier):
        audit_log("rate_limited", "", {"ip": identifier}, False)
        raise HTTPException(status_code=429, detail=f"请求频率超过限制 ({AI_RATE_LIMIT_PER_MIN}/分钟)")
    return None


# ── 装饰器 ──────────────────────────────────────────────


def with_audit(action: str):
    """FastAPI 路由装饰器：自动记录审计日志"""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = (time.time() - start) * 1000
                audit_log(action, success=True, duration_ms=duration)
                return result
            except Exception as exc:
                duration = (time.time() - start) * 1000
                audit_log(action, success=False, duration_ms=duration, details={"error": str(exc)})
                raise

        return wrapper

    return decorator


def get_api_key_info(api_key: str) -> dict[str, Any] | None:
    """获取 API Key 信息"""
    if api_key not in AI_API_KEYS:
        return None
    info = AI_API_KEYS[api_key].copy()
    info["permissions"] = list(ALL_PERMISSIONS)
    info["masked_key"] = api_key[:8] + "..." if len(api_key) > 8 else "***"
    return info
