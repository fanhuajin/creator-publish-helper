"""验证本地Windows-MCP安装、协议初始化及工具发现；不调用桌面工具。"""
import asyncio
import json
import os
from importlib.metadata import version
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check():
    command=Path.home()/".local"/"bin"/"windows-mcp.exe"
    if not command.is_file():
        raise FileNotFoundError(f"未找到已安装的Windows-MCP：{command}")
    params=StdioServerParameters(command=str(command),args=["serve"],
        env={**os.environ,"ANONYMIZED_TELEMETRY":"false","PYTHONIOENCODING":"utf-8"})
    async with asyncio.timeout(45):
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write,read_timeout_seconds=30) as session:
                initialized=await session.initialize()
                listed=await session.list_tools()
                names=sorted(tool.name for tool in listed.tools)
                required={"Snapshot","Screenshot","Scroll","Click"}
                if not required.issubset(names):
                    raise RuntimeError(f"Windows-MCP工具缺失：{sorted(required-set(names))}")
                print(json.dumps({"ok":True,"command":str(command),
                    "package_version":version("windows-mcp"),
                    "server":initialized.server_info.model_dump(by_alias=True),"tools":names,
                    "desktop_tools_called":False},ensure_ascii=False))


if __name__=="__main__":
    asyncio.run(check())
