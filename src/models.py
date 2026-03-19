from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IPODetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_share_id: str = Field(..., min_length=1, description="Company Share ID")
    units: int = Field(..., ge=1, description="Number of units (kitta)")
    bank: str = Field(..., min_length=1, description="Bank name for ASBA")


class ApplyIPORequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dp_id: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    crn: str = Field(..., min_length=1)
    pin: str = Field(..., min_length=1)
    ipo_details: IPODetails


class ApplyIPOResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "error"]
    message: str
    application_id: Optional[str] = None
    details: Optional[Dict[str, str]] = None
    timestamp: str
    request_id: str
    duration_ms: int


class CheckAllotmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dp_id: str = Field(..., min_length=1, alias="dpId")
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    ipo_name: str = Field(..., min_length=1, description="IPO name or company share id", alias="ipoName")
    credentials: Optional["CredentialsPayload"] = None

    @model_validator(mode="before")
    @classmethod
    def _unpack_credentials(cls, data):
        if isinstance(data, dict) and data.get("credentials"):
            creds = data["credentials"] or {}
            data = {**data}
            if "dp_id" not in data and "dpId" not in data:
                data["dp_id"] = creds.get("dpId") or creds.get("dp_id")
            data.setdefault("username", creds.get("username"))
            data.setdefault("password", creds.get("password"))
        return data


class CheckAllotmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    status: str
    is_allotted: bool
    allotted_quantity: str
    all_details: Dict[str, str]
    timestamp: str
    message: Optional[str] = None
    request_id: str
    duration_ms: int


class PortfolioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dp_id: str = Field(..., min_length=1, alias="dpId")
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    credentials: Optional["CredentialsPayload"] = None

    @model_validator(mode="before")
    @classmethod
    def _unpack_credentials(cls, data):
        if isinstance(data, dict) and data.get("credentials"):
            creds = data["credentials"] or {}
            data = {**data}
            if "dp_id" not in data and "dpId" not in data:
                data["dp_id"] = creds.get("dpId") or creds.get("dp_id")
            data.setdefault("username", creds.get("username"))
            data.setdefault("password", creds.get("password"))
        return data


class PortfolioItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    units: float
    current_price: float
    buy_price: float


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    portfolio: List[PortfolioItem]
    message: Optional[str] = None
    timestamp: str
    request_id: str
    duration_ms: int
    total_positions: Optional[int] = None
    total_units: Optional[float] = None


class TestLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dp_id: str = Field(..., min_length=1, alias="dpId")
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    credentials: Optional["CredentialsPayload"] = None

    @model_validator(mode="before")
    @classmethod
    def _unpack_credentials(cls, data):
        if isinstance(data, dict) and data.get("credentials"):
            creds = data["credentials"] or {}
            data = {**data}
            if "dp_id" not in data and "dpId" not in data:
                data["dp_id"] = creds.get("dpId") or creds.get("dp_id")
            data.setdefault("username", creds.get("username"))
            data.setdefault("password", creds.get("password"))
        return data


class CredentialsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    dp_id: str = Field(..., min_length=1, alias="dpId")
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TestLoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str
    timestamp: str
    request_id: str
    duration_ms: int


class DpsItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    code: str

