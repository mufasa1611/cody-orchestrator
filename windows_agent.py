from crewai import Agent
from llm import llm
from tools.windows_cmd import run_windows_command

windows_agent = Agent(
    name="Windows Admin",
    role="Controls and automates Windows tasks",
    goal="Execute Windows commands safely and correctly based on user requests.",
    backstory=(
        "You are a senior Windows system administrator. "
        "You use the windows_command tool to run PowerShell commands when needed."
    ),
    llm=llm,
    tools=[run_windows_command],
    allow_delegation=False,
    verbose=True,
)