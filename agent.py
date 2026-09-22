"""
agent.py
Conversational asset management agent using Azure OpenAI function calling.

The agent has access to five tools:
  1. search_assets(query)
  2. get_high_risk_assets(threshold)
  3. schedule_maintenance(asset_id)       → PROPOSAL only, never executed
  4. reallocate_asset(asset_id, to_dept, to_location) → PROPOSAL only
  5. search_policy_docs(query)            → vector search on Azure AI Search

Rules encoded in the system prompt:
  - Never call execute_action() — only propose.
  - Always cite source_file when answering policy questions.
  - Relay errors from tools clearly.

Run:
    python agent.py

Required .env variables:
    AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_KEY, AZURE_CHAT_DEPLOYMENT,
    AZURE_EMBEDDING_DEPLOYMENT,
    AZURE_SEARCH_ENDPOINT, AZURE_SEARCH_KEY, AZURE_SEARCH_INDEX
"""

import json
import os

import pandas as pd
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery

# ── import the five existing tools (no execute_action) ───────────────────────
from tools import (
    search_assets,
    get_high_risk_assets,
    get_underused_assets,
    schedule_maintenance,
    reallocate_asset,
)

load_dotenv()

# ── config ────────────────────────────────────────────────────────────────────
FOUNDRY_ENDPOINT   = os.environ["AZURE_FOUNDRY_ENDPOINT"].rstrip("/")
FOUNDRY_KEY        = os.environ["AZURE_FOUNDRY_KEY"]
CHAT_DEPLOYMENT    = os.environ["AZURE_CHAT_DEPLOYMENT"]
EMBED_DEPLOYMENT   = os.environ["AZURE_EMBEDDING_DEPLOYMENT"]
SEARCH_ENDPOINT    = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY         = os.environ["AZURE_SEARCH_KEY"]
INDEX_NAME         = os.environ["AZURE_SEARCH_INDEX"]

# ── clients (same pattern as index_docs.py / test_search.py) ─────────────────
openai_client = AzureOpenAI(
    azure_endpoint=FOUNDRY_ENDPOINT,
    api_key=FOUNDRY_KEY,
    api_version="2024-10-21",
)

search_client = SearchClient(
    endpoint=SEARCH_ENDPOINT,
    index_name=INDEX_NAME,
    credential=AzureKeyCredential(SEARCH_KEY),
)

# ── system prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are an asset management assistant for a university IT department. "
    "Use the provided tools to answer questions about assets and policies. "
    "Never call execute_action yourself — only propose actions using "
    "schedule_maintenance or reallocate_asset, then tell the user the action "
    "needs human approval before anything is written to the database. "
    "When a tool returns an error field, relay that error clearly to the user "
    "instead of proceeding. "
    "When answering policy questions, always cite the source_file from "
    "search_policy_docs results — do not invent policy content. "
    "When the user asks about 'underused', 'idle', 'low utilization', or "
    "'underutilized' assets, always call get_underused_assets — never "
    "search_assets — even if they also mention a specific type like 'laptops'. "
    "Pass the type as the asset_type argument."
)

# ── tool schemas (OpenAI function-calling format) ─────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_assets",
            "description": (
                "Search for assets by keyword. Matches against asset ID, type, "
                "department, and location. Returns a list of matching assets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keyword to search for, e.g. 'laptop' or 'Biology'.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_high_risk_assets",
            "description": (
                "Return in-service assets (Active, Idle, or Under Repair) whose "
                "repair risk score is at or above the given threshold (0–100). "
                "Sorted highest risk first. Default threshold is 60."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {
                        "type": "integer",
                        "description": "Minimum repair risk score to include (0–100). Default 60.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_maintenance",
            "description": (
                "Propose a maintenance action for a given asset. "
                "Returns a PROPOSAL dict — it does NOT update the database. "
                "The proposal must be approved by a human before anything is written. "
                "Returns an error if the asset does not exist, is Decommissioned, "
                "or has another blocking condition."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "The asset ID, e.g. 'ASSET-0009'.",
                    }
                },
                "required": ["asset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reallocate_asset",
            "description": (
                "Propose moving an asset to a different department and location. "
                "Returns a PROPOSAL dict — it does NOT update the database. "
                "The proposal must be approved by a human before anything is written. "
                "Returns an error if the asset does not exist, is Decommissioned, "
                "is Under Repair, or if the target department is the same as the current one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_id": {
                        "type": "string",
                        "description": "The asset ID to reallocate, e.g. 'ASSET-0004'.",
                    },
                    "to_dept": {
                        "type": "string",
                        "description": "Target department name, e.g. 'Physics'.",
                    },
                    "to_location": {
                        "type": "string",
                        "description": "Target location, e.g. 'Building B - Room 204'.",
                    },
                },
                "required": ["asset_id", "to_dept", "to_location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy_docs",
            "description": (
                "Search the university asset policy documents using semantic (vector) search. "
                "Returns the top 3 matching chunks with their source_file. "
                "Use this tool to answer any question about maintenance intervals, "
                "replacement thresholds, audit rules, or allocation policy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural-language question or keyword about policy.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_underused_assets",
            "description": (
                "Return assets that are flagged as underused (low utilization / idle). "
                "Only Active and Idle assets can be underused. "
                "Use this tool — not search_assets — whenever the user asks about "
                "'underused', 'idle', 'low utilization', or 'underutilized' assets. "
                "Optionally filter by asset type (e.g. 'laptop'). "
                "Returns an empty list when no underused assets match."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_type": {
                        "type": "string",
                        "description": (
                            "Optional asset type to filter by, e.g. 'laptop' or 'laptops'. "
                            "Omit to return all underused assets regardless of type."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
]


# ── tool 5: search_policy_docs ────────────────────────────────────────────────
def search_policy_docs(query: str, top: int = 3) -> str:
    """
    Embed the query, run a vector search against the Azure AI Search index,
    and return the top-k results as a JSON string with content and source_file.
    Returned as a string so it can be passed back as a tool message.
    """
    # Embed the query using the same embedding model as index_docs.py
    embed_response = openai_client.embeddings.create(
        model=EMBED_DEPLOYMENT,
        input=[query],
    )
    query_vector = embed_response.data[0].embedding

    vector_query = VectorizedQuery(
        vector=query_vector,
        k_nearest_neighbors=top,
        fields="embedding",
    )

    results = search_client.search(
        search_text=None,
        vector_queries=[vector_query],
        select=["content", "source_file"],
        top=top,
    )

    chunks = []
    for r in results:
        chunks.append({
            "source_file": r.get("source_file", "unknown"),
            "content":     r.get("content", ""),
            "score":       round(r.get("@search.score", 0.0), 4),
        })

    return json.dumps(chunks, ensure_ascii=False)


# ── tool dispatcher ───────────────────────────────────────────────────────────
def dispatch_tool(name: str, args: dict) -> str:
    """
    Call the right Python function for a given tool name and return its result
    as a JSON string suitable for a 'tool' role message.

    DataFrames are converted to a trimmed list-of-dicts (max 20 rows) so the
    model receives readable text rather than a pandas repr.
    """
    def df_to_json(df: pd.DataFrame, max_rows: int = 20) -> str:
        cols = ["id", "type", "dept", "status", "repair_risk", "usage_hours", "reason"]
        available = [c for c in cols if c in df.columns]
        trimmed = df[available].head(max_rows)
        return trimmed.to_json(orient="records", indent=2)

    if name == "search_assets":
        result = search_assets(args["query"])
        return df_to_json(result)

    elif name == "get_high_risk_assets":
        threshold = args.get("threshold", 60)
        result = get_high_risk_assets(threshold)
        return df_to_json(result)

    elif name == "schedule_maintenance":
        result = schedule_maintenance(args["asset_id"])
        return json.dumps(result, ensure_ascii=False)

    elif name == "reallocate_asset":
        result = reallocate_asset(
            asset_id=args["asset_id"],
            new_dept=args["to_dept"],
            new_location=args["to_location"],
        )
        return json.dumps(result, ensure_ascii=False)

    elif name == "search_policy_docs":
        return search_policy_docs(args["query"])

    elif name == "get_underused_assets":
        asset_type = args.get("asset_type")   # optional — may be None
        result = get_underused_assets(asset_type)
        return df_to_json(result)

    else:
        return json.dumps({"error": f"Unknown tool: '{name}'"})


# ── core agent loop ───────────────────────────────────────────────────────────
def run_agent(user_message: str) -> dict:
    """
    Run one conversation turn:
      1. Send system prompt + user message to the model with tools available.
      2. While the model returns tool_calls, dispatch each tool and feed results back.
      3. Return the final text response and a log of every tool call made.

    Returns:
        {
          "response": str,              # final model text
          "tool_calls": [               # list of {name, args, result_preview}
              {"name": ..., "args": ..., "result_preview": ...}, ...
          ]
        }
    """
    messages = [
        {"role": "system",  "content": SYSTEM_PROMPT},
        {"role": "user",    "content": user_message},
    ]
    tool_call_log = []

    # Agentic loop — keep going while the model wants to call tools
    for _turn in range(6):   # safety cap: max 6 tool-call rounds per query
        completion = openai_client.chat.completions.create(
            model=CHAT_DEPLOYMENT,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )

        response_message = completion.choices[0].message
        # Append the assistant message (may contain tool_calls)
        messages.append(response_message)

        if not response_message.tool_calls:
            # No more tool calls — we have the final answer
            break

        # Dispatch every tool call the model requested
        for tc in response_message.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)

            tool_result = dispatch_tool(fn_name, fn_args)

            # Log for printing in the smoke test
            tool_call_log.append({
                "name":           fn_name,
                "args":           fn_args,
                "result_preview": tool_result[:200] + ("…" if len(tool_result) > 200 else ""),
            })

            # Feed the result back as a tool message
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "name":         fn_name,
                "content":      tool_result,
            })

    final_text = response_message.content or "(no text response)"
    return {"response": final_text, "tool_calls": tool_call_log}


# ── smoke test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TEST_MESSAGES = [
        "Which assets need repair?",
        "Show underused laptops",
        "What does the maintenance policy say about intervals?",
        "Reallocate an underused asset",
    ]

    SEP  = "═" * 70
    SEP2 = "─" * 70

    print(f"\n{SEP}")
    print("  AI Asset Rescue Agent — smoke test")
    print(f"  Model: {CHAT_DEPLOYMENT}  |  Tools: {len(TOOLS)}")
    print(SEP)

    for i, msg in enumerate(TEST_MESSAGES, start=1):
        print(f"\n[{i}/{len(TEST_MESSAGES)}] USER: {msg}")
        print(SEP2)

        result = run_agent(msg)

        if result["tool_calls"]:
            print(f"  Tool calls made: {len(result['tool_calls'])}")
            for tc in result["tool_calls"]:
                print(f"    → {tc['name']}({json.dumps(tc['args'])})")
                print(f"      result preview: {tc['result_preview']}")
        else:
            print("  (no tool calls)")

        print(f"\n  AGENT: {result['response']}")
        print(SEP)
