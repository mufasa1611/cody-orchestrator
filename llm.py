from langchain_ollama import OllamaLLM

llm = OllamaLLM(
    model="gemma4:26b",
    temperature=0.2,
    num_ctx=32768,
)