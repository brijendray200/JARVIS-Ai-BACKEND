from duckduckgo_search import DDGS

class SearchService:
    def __init__(self):
        self.ddgs = DDGS()

    def search(self, query: str, max_results: int = 3) -> str:
        try:
            results = self.ddgs.text(query, max_results=max_results)
            if not results:
                return "No results found."
            
            formatted_results = ""
            for i, res in enumerate(results):
                formatted_results += f"Result {i+1}:\n"
                formatted_results += f"Title: {res.get('title', 'No Title')}\n"
                formatted_results += f"Body: {res.get('body', 'No Body')}\n\n"
            return formatted_results.strip()
        except Exception as e:
            print(f"Error in web search: {e}")
            return f"Error executing search: {str(e)}"
