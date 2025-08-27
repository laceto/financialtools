from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Optional
from langchain_core.output_parsers import PydanticOutputParser

# Pydantic output model
class StockRegimeAssessment(BaseModel):
    regime: Literal["bull", "bear"] = Field(
        ..., description="The fundamental regime classification of the stock"
    )
    rationale: str = Field(
        ..., description="Concise explanation justifying the regime classification based on the financial metrics, composite ratio and red flags"
    )
    metrics_movement: str = Field(
        ..., description=(
            "A summary description of how key financial metrics have moved across years, "
            "e.g., 'GrossMargin increased steadily, DebtToEquity rose sharply, FCFYield remained stable.'"
        )
    )
    non_aligned_findings: Optional[str] = Field(
        None,
        description=(
            "Observations or signals that are not aligned with the overall metric trends, "
            "such as contradictory indicators, anomalies."
        )
    )