from financialtools.utils import *

from dotenv import load_dotenv, find_dotenv 
import pandas as pd
import polars as pl
import json
from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Optional
from langchain_core.output_parsers import PydanticOutputParser
from langchain.output_parsers import OutputFixingParser
from langchain_core.prompts import ChatPromptTemplate
from openai import OpenAI

load_dotenv()
client = OpenAI()

class StockRegimeAssessment(BaseModel):
    ticker: str = Field(..., description="The ticker of the stock under analysis")
    regime: Literal["bull", "bear", "postpone"] = Field(
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
            "such as contradictory indicators, anomalies, or important red flags."
        )
    )

system_prompt_template = """
You are a trader assistant specializing in fundamental analysis. 

Based on the following financial data, provide a concise overall assessment that classifies 
the stock’s current fundamental regime as one of:

- bull: Strong and improving fundamentals supporting a positive outlook.
- bear: Weak or deteriorating fundamentals indicating risk or decline.
- postpone: Mixed or inconclusive fundamentals suggesting to wait for clearer signals.

Financial data constists of financial metrics, composite score and red flags.

Profitability and Margin Metrics:
    -GrossMargin: gross profit / total revenue 
    -OperatingMargin: operating income / total revenue
    -NetProfitMargin: net income / total revenue
    -EBITDAMargin: ebitda / total revenue
Returns metrics:
    -ROA: net income / total assets
    -ROE: net income / total equity
Cash Flow Strength metrics: 
    -FCFToRevenue: free cash flow / total revenue
    -FCFYield: free cash flow / market capitalization
    -FCFToDebt:: free cash flow / total debt
Leverage & Solvency metrics:
    -DebtToEquity: total debt / total equity
Liquidity metrics:
    -CurrentRatio: working capital / total liabilities

The composite score is a weighted average (1 to 5) that summarizes the company’s overall fundamental health.
It reflects profitability, efficiency, leverage, liquidity, and cash flow strength, based on the above mentioned financial metrics.

Range:
1 = Weak fundamentals
5 = Strong fundamentals

Each metric is scored on a 1–5 scale and multiplied by its weight. The composite score is the sum of weighted scores divided by the total weight.

A red flag is an early warning signal that highlights potential weaknesses in a company’s financial statements 
or business quality. These warnings do not always mean immediate distress, but they indicate heightened risk that 
traders should carefully consider before taking a position.

"""

tickers = get_ticker_list()
tickers = tickers[:1]

metrics_str = get_fin_data(tickers[0])
metrics_str = metrics_str.to_dict()
metrics_str = json.dumps(metrics_str)
# print(metrics_str)


import rich
completion = client.beta.chat.completions.parse(
    model="gpt-4.1-nano",
    messages=[
        {"role": "system", "content": system_prompt_template},
        {"role": "user", "content": metrics_str},
    ],
    response_format=StockRegimeAssessment,
)

message = completion.choices[0].message
if message.refusal:
    rich.print(message.refusal)
else:
    event = message.parsed
    rich.print(event)