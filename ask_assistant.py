from dotenv import load_dotenv, find_dotenv 
import pandas as pd
import polars as pl
import json
from pydantic import BaseModel, Field
from typing import Literal, List, Dict, Optional
from langchain_core.output_parsers import PydanticOutputParser
from langchain.output_parsers import OutputFixingParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from financialtools.utils import *

load_dotenv()

metrics = (pl.from_pandas(pd.read_excel('financialtools/data/metrics.xlsx'))
    .filter(pl.col("ticker") == "CPR.MI")
    .to_pandas())
metrics = metrics.to_json(orient="records") 

composite_scores = (pl.from_pandas(pd.read_excel('financialtools/data/composite_scores.xlsx'))
    .filter(pl.col("ticker") == "CPR.MI")
    .to_pandas())
composite_scores = composite_scores.to_json(orient="records") 

red_flags = pl.concat([
    (pl.from_pandas(pd.read_excel('financialtools/data/red_flags.xlsx'))
        .filter(pl.col("ticker") == "CPR.MI")),
    (pl.from_pandas(pd.read_excel('financialtools/data/raw_red_flags.xlsx'))
        .filter(pl.col("ticker") == "CPR.MI"))]
).to_pandas()
red_flags = red_flags.to_json(orient="records") 

# Pydantic output model
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


# Instantiate the LLM (OpenAI GPT-4 or your preferred model)
llm = ChatOpenAI(model="gpt-4.1-nano", temperature=0)

# Instantiate the parser with the Pydantic model
parser = PydanticOutputParser(pydantic_object=StockRegimeAssessment)
# Wrap your parser with OutputFixingParser
parser = OutputFixingParser.from_llm(parser=parser, llm=llm)

# Get the format instructions string from the parser
format_instructions = parser.get_format_instructions()

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

# Create a ChatPromptTemplate with system message and user input

system_prompt_filled = system_prompt_template.format(format_instructions=format_instructions)

prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt_filled),
    ("human", "The ticker is:\n{ticker}\nMetrics:\n{metrics}\nScores:\n{scores}\nRedFlags:\n{red_flags}"),
])

# Create a runnable chain: prompt followed by LLM invocation
chain = prompt | llm | parser

ticker_str = 'CPR.MI'
# metrics_str = json.dumps(metrics, indent=2)
# scores_str = json.dumps(composite_scores, indent=2)
# red_flags_str = json.dumps(red_flags, indent=2)

metrics_str = get_fin_data('CPR.MI')

# metrics_str = metrics_str.round(2)
metrics_str = metrics_str.to_dict()
metrics_str = json.dumps(metrics_str)

print(metrics_str)

# Then invoke with a dict containing 'financial_data'
# response = chain.invoke({
#     "ticker": ticker_str,
#     "metrics": metrics_str,  
#     "scores": scores_str,
#     "red_flags": red_flags_str,    
# })

# print(response)

# print(response.model_dump_json())

# prompt_value = prompt.invoke({
#     "ticker": ticker_str,
#     "metrics": metrics_str,  
#     "scores": scores_str,
#     "red_flags": red_flags_str,    
# })

# print(prompt_value.messages[0].content[0])
# print(prompt_value.messages[1].content[0])


# from financialtools.utils import *

# tickers = get_ticker_list()
# tickers = tickers[:2]

# financial_data = [get_fin_data(ticker) for ticker in tickers]

