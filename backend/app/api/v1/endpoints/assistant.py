from fastapi import APIRouter
from app.services.llm_service import chat
from app.schemas.api import ChatRequest, ChatResponse

router = APIRouter(prefix="/assistant", tags=["LLM Assistant (UC4)"])


@router.post("/chat", response_model=ChatResponse, summary="Chat with the financial data assistant")
async def assistant_chat(req: ChatRequest):
    """
    UC4 — LLM-powered assistant grounded in platform data.
    The assistant can call DWH tools: list_assets, get_stats, forecast, compare, etc.
    Set ANTHROPIC_API_KEY in .env to enable.

    Example prompts:
    - "What stocks are available?"
    - "Show me AAPL stats for 2024"
    - "Forecast TSLA for the next 5 days"
    - "Compare AAPL and MSFT performance"
    """
    return await chat(req)
