from __future__ import annotations

from crewai.tools import BaseTool

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None


class WebSearchTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Search the web for documentation, error solutions, or technical information. "
        "Returns a list of relevant snippets and links."
    )

    def _run(self, query: str) -> str:
        if DDGS is None:
            return "Error: duckduckgo-search package not installed. Run 'pip install duckduckgo-search'."
        
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=5))
                if not results:
                    return f"No web results found for '{query}'."
                
                parts = []
                for r in results:
                    parts.append(f"Title: {r.get('title')}\nSnippet: {r.get('body')}\nURL: {r.get('href')}")
                
                return "\n\n---\n\n".join(parts)
        except Exception as e:
            return f"Error performing web search: {e}"
