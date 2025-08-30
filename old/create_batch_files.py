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

from financialtools.pydantic_models import StockRegimeAssessment
from financialtools.prompts import system_prompt_StockRegimeAssessment
from financialtools.wrappers import read_financial_results
from financialtools.utils import dataframe_to_json

load_dotenv()
client = OpenAI()



tickers = get_tickers(columns='ticker').to_list()[:1]

Structured_Response = to_strict_json_schema(StockRegimeAssessment)



tasks = []
for ticker in tickers:
    
    metrics, eval_metrics, composite_scores, red_flags = read_financial_results(
        ticker=ticker,
        # time=year,
        input_dir='financial_data', 
        sheet_name='sheet1')

    metrics, eval_metrics, composite_scores, red_flags = [
        dataframe_to_json(df)
        for df in [metrics, eval_metrics, composite_scores, red_flags]
    ]

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
                    "content": system_prompt_StockRegimeAssessment
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

file_name = "batch_files/batch_tasks_tickers.jsonl"

with open(file_name, 'w') as file:
    for obj in tasks:
        file.write(json.dumps(obj) + '\n')


# Uploading the file
batch_file = client.files.create(
  file=open(file_name, "rb"),
  purpose="batch"
)

print(batch_file)

# # Creating the batch job
# batch_job = client.batches.create(
#   input_file_id=batch_file.id,
#   endpoint="/v1/chat/completions",
#   completion_window="24h"
# )

# print(batch_job)