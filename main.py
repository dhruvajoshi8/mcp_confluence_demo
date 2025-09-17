import os
import httpx
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

CONFLUENCE_BASE = os.getenv("CONFLUENCE_BASE")
CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
DEFAULT_SPACE = os.getenv("CONFLUENCE_SPACE_KEY", "DEMO")

app = FastAPI()

def success(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}

def error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}

async def confluence_get(url: str):
    async with httpx.AsyncClient(auth=(CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()

async def confluence_post(url: str, payload: dict):
    async with httpx.AsyncClient(auth=(CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

async def confluence_put(url: str, payload: dict):
    async with httpx.AsyncClient(auth=(CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)) as client:
        r = await client.put(url, json=payload)
        r.raise_for_status()
        return r.json()

@app.post("/rpc")
async def rpc_handler(req: Request):
    body = await req.json()
    method = body.get("method")
    params = body.get("params", {})
    id_ = body.get("id")

    try:
        # 1) List pages
        if method == "resources.listPages":
            space_key = params.get("spaceKey", DEFAULT_SPACE)
            query = params.get("query", "")
            cql = f'space="{space_key}"'
            if query:
                cql += f' and title~"{query}"'
            url = f"{CONFLUENCE_BASE}/wiki/rest/api/content/search?cql={cql}&limit=25&expand=body.storage,version"
            data = await confluence_get(url)
            pages = [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "excerpt": p.get("body", {}).get("storage", {}).get("value", "")[:400],
                }
                for p in data.get("results", [])
            ]
            return success(id_, pages)

        # 2) Get page
        if method == "resources.getPage":
            if "id" in params:
                page_id = params["id"]
                url = f"{CONFLUENCE_BASE}/wiki/rest/api/content/{page_id}?expand=body.storage,version,space"
                data = await confluence_get(url)
                return success(id_, data)
            elif "title" in params:
                space_key = params.get("spaceKey", DEFAULT_SPACE)
                title = params["title"]
                cql = f'space="{space_key}" and title="{title}"'
                url = f"{CONFLUENCE_BASE}/wiki/rest/api/content/search?cql={cql}&limit=1&expand=body.storage,version"
                data = await confluence_get(url)
                if data.get("size", 0) == 0:
                    return error(id_, -32001, "Page not found")
                return success(id_, data["results"][0])
            else:
                return error(id_, -32602, "missing id or title parameter")

        # 3) Create page
        if method == "tools.createPage":
            space_key = params.get("spaceKey", DEFAULT_SPACE)
            payload = {
                "type": "page",
                "title": params.get("title", "Untitled page (MCP demo)"),
                "space": {"key": space_key},
                "body": {
                    "storage": {
                        "value": params.get("bodyHtml", "<p>Created by MCP demo</p>"),
                        "representation": "storage",
                    }
                },
            }
            if "parentId" in params:
                payload["ancestors"] = [{"id": params["parentId"]}]
            url = f"{CONFLUENCE_BASE}/wiki/rest/api/content"
            data = await confluence_post(url, payload)
            return success(id_, data)

        # 4) Update page
        if method == "tools.updatePage":
            if "id" not in params:
                return error(id_, -32602, "missing id parameter")
            page_id = params["id"]
            get_url = f"{CONFLUENCE_BASE}/wiki/rest/api/content/{page_id}?expand=version,body.storage"
            existing = await confluence_get(get_url)
            cur_version = existing["version"]["number"]
            title = params.get("title", existing["title"])
            payload = {
                "id": page_id,
                "type": "page",
                "title": title,
                "version": {"number": cur_version + 1},
                "body": {
                    "storage": {
                        "value": params.get("bodyHtml", existing["body"]["storage"]["value"]),
                        "representation": "storage",
                    }
                },
            }
            put_url = f"{CONFLUENCE_BASE}/wiki/rest/api/content/{page_id}"
            data = await confluence_put(put_url, payload)
            return success(id_, data)

        # Default
        return error(id_, -32601, "Method not found")

    except httpx.HTTPStatusError as e:
        return error(id_, -32000, f"HTTP error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        return error(id_, -32000, str(e))
