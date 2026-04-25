import pytest
from unittest.mock import patch, MagicMock
from crew_agent.handlers.orchestrator import run_request
from crew_agent.core.models import ExecutionPlan, PlanStep, StepExecutionResult

def test_transcript_nmap_recovery(mock_ui):
    """
    Scenario: User asks for host discovery.
    1. Planner suggests 'nmap'.
    2. Execution fails (nmap not installed).
    3. Orchestrator MUST re-plan.
    4. New plan uses 'arp -a' and succeeds.
    """
    mock_host = MagicMock()
    mock_host.name = "local-win"
    mock_host.platform = "windows"
    mock_host.transport = "local"

    # The plan that fails
    nmap_plan = ExecutionPlan(
        summary="Scan with nmap",
        steps=[PlanStep(id="s1", title="Scan", host="local-win", command="nmap -sn 192.168.1.0/24", kind="discovery")],
        target_hosts=["local-win"],
        raw={"domain": "infra"}
    )

    # The plan that recovers
    arp_plan = ExecutionPlan(
        summary="Scan with arp",
        steps=[PlanStep(id="s2", title="ARP Scan", host="local-win", command="arp -a", kind="discovery")],
        target_hosts=["local-win"],
        raw={"domain": "infra"}
    )

    fail_result = StepExecutionResult(
        step_id="s1", host="local-win", title="Scan", command="nmap...",
        success=False, returncode=1, stdout="", stderr="'nmap' is not recognized",
        duration_seconds=0.1, verify=None
    )
    success_result = StepExecutionResult(
        step_id="s2", host="local-win", title="ARP Scan", command="arp -a",
        success=True, returncode=0, stdout="192.168.1.1 ...", stderr="",
        duration_seconds=0.1, verify=None
    )

    with patch("crew_agent.handlers.orchestrator.load_inventory", return_value=[mock_host]), \
         patch("crew_agent.handlers.orchestrator.plan_request", return_value=(nmap_plan, [mock_host])), \
         patch("crew_agent.handlers.orchestrator.execute_plan_step") as mock_exec, \
         patch("crew_agent.handlers.orchestrator.create_execution_plan", return_value=arp_plan):
        
        mock_exec.side_effect = [fail_result, success_result]
        
        exit_code = run_request("discover hosts", mock_ui)
        
        assert exit_code == 0
        assert mock_exec.call_count == 2
        # Verify that we tried 'nmap' first, then 'arp -a'
        assert "nmap" in mock_exec.call_args_list[0][0][0].command
        assert "arp -a" in mock_exec.call_args_list[1][0][0].command
