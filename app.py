import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from typing import Any

from dotenv import load_dotenv
#from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY:
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# if GROQ_API_KEY:
#     os.environ["GROQ_API_KEY"] = GROQ_API_KEY

STREAMABLE_HTTP_URL = os.getenv("GDRIVE_MCP_URL", "http://127.0.0.1:8000/mcp")
SERVER_STARTUP_DELAY = float(os.getenv("GDRIVE_MCP_STARTUP_DELAY", "1.0"))


def _print_tool_calls(messages: Sequence[Any]) -> None:
    """Print tool invocation names/args found in the agent trace."""
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            continue

        for call in tool_calls:
            if isinstance(call, Mapping):
                name = call.get("name", "<unknown>")
                args = call.get("args")
            else:
                name = getattr(call, "name", "<unknown>")
                args = getattr(call, "args", None)
            print(f"Tool call '{name}' args: {args}")


async def _launch_gdrive_mcp_server() -> asyncio.subprocess.Process:
    """Start the FastMCP Google Drive server for streamable HTTP transport."""
    env = os.environ.copy()
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credentials_path:
        env["GDRIVE_CREDENTIALS_PATH"] = credentials_path
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "gdrive_mcp_server.py",
        env=env,
    )


async def main() -> None:
    server_process = await _launch_gdrive_mcp_server()
    try:
        await asyncio.sleep(SERVER_STARTUP_DELAY)
        if server_process.returncode is not None:
            raise RuntimeError("Google Drive MCP server exited before startup completed")

        client = MultiServerMCPClient(
            {
                "gdrive": {
                    "transport": "streamable_http",
                    "url": STREAMABLE_HTTP_URL,
                }
            }
        )

        print("Loading MCP tools...")
        tools = await client.get_tools()
        print(f"Loaded tools: {[tool.name for tool in tools]}")

        model = ChatOpenAI(model="gpt-4o")
        agent = create_react_agent(model, tools)

        system_prompt = (
            "You are a Google Drive assistant. "
            "Only answer questions related to Google Drive files and folders. "
            "Use the provided tools to interact with Google Drive."
        )

        user_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "read file 'CREDIT CARD FRAUD DETECTION.pptx' and summarize it"},
        ]

        response = await agent.ainvoke({"messages": user_messages})
        _print_tool_calls(response.get("messages", []))
        print("Agent Response:", response["messages"][-1].content)
    finally:
        if server_process.returncode is None:
            server_process.terminate()
            try:
                await asyncio.wait_for(server_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                server_process.kill()
                await server_process.wait()


if __name__ == "__main__":
    asyncio.run(main())

