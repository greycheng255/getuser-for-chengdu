# -*- coding: utf-8 -*-
"""统一账号管理 API。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.schemas.accounts import (
    AccountBatchCreateRequest,
    AccountBatchCreateResponse,
    AccountCreateRequest,
    AccountListResponse,
    AccountResponse,
    AccountRole,
    AccountStatsResponse,
    AccountStatus,
    AccountUpdateRequest,
)
from api.services.auth import get_current_user, is_admin
from api.services.unified_account_service import (
    AccountNotFoundError,
    DuplicateAccountError,
    UnifiedAccountError,
    get_unified_account_service,
)

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _owner_scope(current_user: dict, requested_owner: Optional[str] = None) -> Optional[str]:
    if is_admin(current_user):
        return requested_owner
    return str(current_user["id"])


def _raise_service_error(exc: Exception) -> None:
    if isinstance(exc, AccountNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, DuplicateAccountError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/stats", response_model=AccountStatsResponse)
async def account_stats(
    owner_user_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    return await service.get_stats(_owner_scope(current_user, owner_user_id))


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    platform: Optional[str] = Query(None),
    role: Optional[AccountRole] = Query(None),
    account_status: Optional[AccountStatus] = Query(None, alias="status"),
    group_name: Optional[str] = Query(None),
    owner_user_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.list_accounts(
            owner_user_id=_owner_scope(current_user, owner_user_id),
            platform=platform,
            role=role,
            status=account_status,
            group_name=group_name,
            page=page,
            page_size=page_size,
        )
    except UnifiedAccountError as exc:
        _raise_service_error(exc)


@router.post("", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    request: AccountCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.create_account(str(current_user["id"]), request)
    except UnifiedAccountError as exc:
        _raise_service_error(exc)


@router.post("/batch", response_model=AccountBatchCreateResponse)
async def batch_create_accounts(
    request: AccountBatchCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    created, failed = await service.batch_create_accounts(str(current_user["id"]), request.items)
    return {"created": created, "failed": failed}


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    owner_user_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.get_account(account_id, _owner_scope(current_user, owner_user_id))
    except UnifiedAccountError as exc:
        _raise_service_error(exc)


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: str,
    request: AccountUpdateRequest,
    owner_user_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.update_account(
            account_id,
            _owner_scope(current_user, owner_user_id),
            request,
        )
    except UnifiedAccountError as exc:
        _raise_service_error(exc)


@router.delete("/{account_id}", response_model=AccountResponse)
async def disable_account(
    account_id: str,
    owner_user_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.disable_account(account_id, _owner_scope(current_user, owner_user_id))
    except UnifiedAccountError as exc:
        _raise_service_error(exc)


@router.post("/{account_id}/reset-cooldown", response_model=AccountResponse)
async def reset_cooldown(
    account_id: str,
    owner_user_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.reset_cooldown(account_id, _owner_scope(current_user, owner_user_id))
    except UnifiedAccountError as exc:
        _raise_service_error(exc)


@router.post("/{account_id}/validate")
async def validate_account(
    account_id: str,
    owner_user_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    service = get_unified_account_service()
    try:
        return await service.validate_local_account(account_id, _owner_scope(current_user, owner_user_id))
    except UnifiedAccountError as exc:
        _raise_service_error(exc)
