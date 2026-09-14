"""Pydantic request models for endpoints whose shape matters for correctness
(auth, scheduling, transitions). Everything else accepts a loosely-typed
dict body (see routers) to keep this file proportionate to a reference
implementation rather than a full generated OpenAPI client."""
from __future__ import annotations
import datetime as dt
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class MfaVerifyRequest(BaseModel):
    loginTicket: str
    code: str


class RefreshRequest(BaseModel):
    refreshToken: str


class TransitionRequest(BaseModel):
    toState: str
    reason: Optional[str] = None


class MaterialAllocationLine(BaseModel):
    materialId: str
    requestedQuantity: float
    unit: Optional[str] = None
    preferredBatchId: Optional[str] = None


class ScheduleRequest(BaseModel):
    processStepId: str
    machineId: str
    operatorId: Optional[str] = None
    requestedStart: dt.datetime
    requestedEnd: dt.datetime
    materialAllocations: list[MaterialAllocationLine] = Field(default_factory=list)


class OverrideCreateRequest(BaseModel):
    conflictType: str
    entityType: str
    entityId: str
    reason: str
    justification: str


class ConsumptionPostingLine(BaseModel):
    consumptionId: str
    quantityConsumed: float


class RunCompletionRequest(BaseModel):
    quantityProduced: float
    postings: list[ConsumptionPostingLine] = Field(default_factory=list)
    partial: bool = False
