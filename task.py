from crewai import Task
from windows_agent import windows_agent

task = Task(
    description=(
        "Restart the Windows audio service (Audiosrv) and then check its status. "
        "Use appropriate PowerShell commands via the windows_command tool."
    ),
    agent=windows_agent,
    expected_output=(
        "Confirmation that the audio service was restarted and its final status."
    ),
)