import pytest
from unittest.mock import patch, MagicMock
from crew_agent.handlers.orchestrator import run_request
from crew_agent.core.models import ExecutionPlan, PlanStep, StepExecutionResult, CommandResult

def test_replan_on_failure(mock_ui):
    """Verify that the orchestrator attempts to re-plan when a step fails."""
    
    # 1. Mock the inventory
    mock_host = MagicMock()
    mock_host.name = "local-win"
    mock_host.platform = "windows"
    mock_host.transport = "local"
    
    # 2. Mock the initial plan (which will fail)
    initial_plan = ExecutionPlan(
        summary="Initial Plan",
        steps=[PlanStep(id="s1", title="Fail Step", host="local-win", command="fail", kind="change")],
        target_hosts=["local-win"],
        raw={"domain": "infra"}
    )
    
    # 3. Mock the refined plan (which will succeed)
    refined_plan = ExecutionPlan(
        summary="Refined Plan",
        steps=[PlanStep(id="s2", title="Success Step", host="local-win", command="succeed", kind="change")],
        target_hosts=["local-win"],
        raw={"domain": "infra"}
    )
    
    # 4. Mock the execution results
    fail_result = StepExecutionResult(
        step_id="s1", host="local-win", title="Fail Step", command="fail",
        success=False, returncode=1, stdout="", stderr="command not found",
        duration_seconds=0.1, verify=None
    )
    success_result = StepExecutionResult(
        step_id="s2", host="local-win", title="Success Step", command="succeed",
        success=True, returncode=0, stdout="success", stderr="",
        duration_seconds=0.1, verify=None
    )

    with patch("crew_agent.handlers.orchestrator.load_inventory", return_value=[mock_host]), \
         patch("crew_agent.handlers.orchestrator.plan_request", return_value=(initial_plan, [mock_host])), \
         patch("crew_agent.handlers.orchestrator.execute_plan_step") as mock_exec, \
         patch("crew_agent.handlers.orchestrator.create_execution_plan", return_value=refined_plan):
        
        # Configure the execution sequence
        mock_exec.side_effect = [fail_result, success_result]
        
        # Run the orchestrator
        exit_code = run_request("test request", mock_ui)
        
        # Verify
        assert exit_code == 0
        assert mock_exec.call_count == 2
        assert mock_ui.phase.called
        # Check that we notified about the replan
        replan_calls = [call for call in mock_ui.phase.call_args_list if "re-plan" in str(call)]
        assert len(replan_calls) > 0
