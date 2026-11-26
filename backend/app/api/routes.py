"""REST routes (PLAN §8): portfolio, watchlist, chat."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..services import PortfolioService, ServiceError


class TradeRequest(BaseModel):
    ticker: str
    quantity: int = Field(gt=0)
    side: Literal["buy", "sell"]


class WatchlistAddRequest(BaseModel):
    ticker: str
    name: str | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _services(request: Request) -> PortfolioService:
    return request.app.state.services


def _http(err: ServiceError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.detail)


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    # ---------------------------------------------------------------- portfolio
    @router.get("/portfolio")
    async def get_portfolio(request: Request) -> dict:
        return await _services(request).portfolio()

    @router.post("/portfolio/trade")
    async def post_trade(body: TradeRequest, request: Request):
        result = await _services(request).trade(body.ticker, body.side, body.quantity)
        if not result.get("success"):
            return JSONResponse(status_code=400, content=result)
        return result

    @router.get("/portfolio/history")
    async def get_history(request: Request) -> list[dict]:
        return await _services(request).history()

    # ---------------------------------------------------------------- watchlist
    @router.get("/watchlist")
    async def get_watchlist(request: Request) -> list[dict]:
        return await _services(request).watchlist()

    @router.post("/watchlist", status_code=201)
    async def post_watchlist(body: WatchlistAddRequest, request: Request) -> dict:
        try:
            return await _services(request).add_watchlist(body.ticker, body.name)
        except ServiceError as e:
            raise _http(e) from e

    @router.delete("/watchlist/{ticker}")
    async def delete_watchlist(ticker: str, request: Request) -> dict:
        try:
            return await _services(request).remove_watchlist(ticker)
        except ServiceError as e:
            raise _http(e) from e

    # --------------------------------------------------------------------- chat
    @router.get("/chat/history")
    async def get_chat_history(request: Request) -> list[dict]:
        return await _services(request).chat_history(50)

    @router.post("/chat")
    async def post_chat(body: ChatRequest, request: Request) -> dict:
        from ..llm import handle_chat  # imported lazily: app.llm is owned by the llm agent

        message = body.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="Message must not be empty")
        return await handle_chat(message, _services(request))

    return router
