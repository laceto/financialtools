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
from pprint import pprint
from openai.lib._pydantic import to_strict_json_schema


load_dotenv()
client = OpenAI()

class StockRegimeAssessment(BaseModel):
    ticker: str = Field(..., description="The ticker of the stock under analysis")
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
            "such as contradictory indicators, anomalies, or important red flags."
        )
    )

system_prompt_template = """
You are a trader assistant specializing in fundamental analysis. 

Based on the following financial data, provide a concise overall assessment that classifies 
the stock’s current fundamental regime as one of:

- bull: Strong and improving fundamentals supporting a positive outlook.
- bear: Weak or deteriorating fundamentals indicating risk or decline.

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
# tickers = tickers[:1]

Structured_Response = to_strict_json_schema(StockRegimeAssessment)

tasks = []
for ticker in tickers:
    
    metrics, composite_scores, red_flags = get_fin_data(ticker, 2024)

    fina_data = f"Metrics:\n{metrics}\nComposite score:\n{composite_scores}\nRed flags:\n{red_flags}\n"
    
    
    task = {
        "custom_id": f"task-{ticker}",
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            # This is what you would have in your Chat Completions API call
            "model": "gpt-4.1-nano",
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                  "name": "structured_response",
                  "schema": Structured_Response,
                  "strict": True
                }
            },
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt_template
                },
                {
                    "role": "user",
                    "content": fina_data
                }
            ],
        }
    }
    
    tasks.append(task)


# Creating the file

file_name = "batch_tasks_tickers.jsonl"

with open(file_name, 'w') as file:
    for obj in tasks:
        file.write(json.dumps(obj) + '\n')


# # Uploading the file
batch_file = client.files.create(
  file=open(file_name, "rb"),
  purpose="batch"
)

print(batch_file)

# Creating the batch job
batch_job = client.batches.create(
  input_file_id=batch_file.id,
  endpoint="/v1/chat/completions",
  completion_window="24h"
)

print(batch_job)