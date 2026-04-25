# cody

`cody` is the first real shell for the Autonomous Infrastructure Orchestrator you described.

## Architecture

The codebase is now organized around the runtime flow:

```text
Conversation Model (LLM)
        ↓
Intent Parser
        ↓
Policy Gate
        ↓
Task Router
   ↙             ↘
Deterministic    Planner Agent
  Handlers
        ↓
Execution Layer
        ↓
Logging / Backups
```

Package layout:

- `src/crew_agent/conversation/`: LLM adapters and front-door request routing
- `src/crew_agent/policy/`: safety, approval, permission, and validation gates
- `src/crew_agent/handlers/`: deterministic handlers, planner handler, task router, orchestrator flow
- `src/crew_agent/executors/`: execution runtime for Windows, SSH, and future transports
- `src/crew_agent/providers/`: inventory plus future external providers such as Proxmox and Synology
- `src/crew_agent/core/`: shared dataclasses, paths, and terminal UI

The older flat modules remain as compatibility shims, but new work should go into the layered packages above.

It is not a full fleet controller yet, but it now behaves like an orchestrator entrypoint instead of a single local script:

- `cody` starts an interactive shell
- `cody "your request"` plans and runs in one shot
- `cody plan "your request"` previews the execution plan
- `cody doctor` validates the local model, inventory, and runtime
- `cody model` opens a model selector, and the old `list` / `set` forms still work
- `cody permissions` opens a permission selector, and the old `show` / `set` forms still work
- `cody approvals set risky|always|never` controls approval gates before execution
- `cody backup set on|off` controls pre-run backup snapshots for `full` mode
- `cody runs list` and `cody runs latest` inspect execution history
- conversational name assignment is stored in `memo.md`
- host inventory is stored in `.cody/hosts.yaml`
- run logs are written to `.cody/runs/`
- backup snapshots for `full` runs are written to `.cody/backups/`
- Windows local execution works now
- Linux over `ssh` and Windows over `winrm` are wired as execution transports when you add hosts to inventory

## Install

From the repo root:

```powershell
venv\Scripts\python.exe -m pip install -e .
```

Then use either:

```powershell
cody
```

or from this folder without relying on PATH:

```powershell
.\cody.cmd
```

To install a global Windows launcher that works from any folder:

```powershell
.\install-cody.ps1
```

This writes `C:\Users\Mufasa\cody.cmd` by default. Since `C:\Users\Mufasa` is already in PATH on this machine, a new shell can run `cody` directly without activating the repo venv.

## First Use

Start the shell:

```powershell
.\cody.cmd
```

One-shot request:

```powershell
.\cody.cmd "Show the installed PowerShell version on the local Windows host"
```

Preview only:

```powershell
.\cody.cmd plan "Check disk space on local-win"
```

Open the model selector:

```powershell
.\cody.cmd model
```

Switch to a different model:

```powershell
.\cody.cmd model set gpt-oss:20b
```

Run with elevated permissions:

```powershell
.\cody.cmd permissions set elevated
.\cody.cmd run "Restart the Windows audio service on local-win"
```

Require approval for risky runs:

```powershell
.\cody.cmd approvals set risky
.\cody.cmd run "Restart the Windows audio service on local-win" --permissions full
.\cody.cmd run "Restart the Windows audio service on local-win" --permissions full --approve
```

Run with full permissions and automatic backup snapshot:

```powershell
.\cody.cmd permissions set full
.\cody.cmd backup set on
.\cody.cmd run "Restart the Windows audio service on local-win"
```

## Interactive Shell

When you run `cody` with no arguments, it opens an interactive shell.

Useful commands inside the shell:

- plain text: runs the request immediately
- `/plan <request>`: preview a plan
- `/doctor`: validate runtime
- `/hosts`: show inventory
- `/status`: show model, permissions, backup mode, and runtime paths
- `/model`: open the model selector
- `/model list`: list models without opening the selector
- `/model set <name>`: set a model directly
- `/permissions`: open the permission selector
- `/permissions safe|elevated|full`: set permissions directly
- `/approvals`: show approval policy
- `/approvals risky|always|never`: change approval policy
- `/agents`: list local specialist agent files
- `/backup`: show backup policy
- `/backup on|off`: change backup policy for `full` mode
- `/runs`: list recent runs
- `/runs latest`: show the newest run summary
- `/exit`: quit

## Local Agents

Cody now has local specialist agent definition files under:

```text
src/crew_agent/agents/definitions/
```

Current built-in local agents include:

- `file-reader`
- `repo-searcher`
- `repo-inspector`
- `test-runner`
- `memory-keeper`
- `workspace-operator`
- `infra-inspector`
- `infra-planner`

These files are loaded locally at runtime and attached to plans as specialist metadata.
You can inspect them with:

```powershell
.\cody.cmd agents list
```

## Inventory

The default inventory is stored in `.cody/hosts.yaml`.

It starts with:

- `local-win`: enabled local Windows host
- `sample-linux`: disabled example SSH host

Example:

```yaml
hosts:
  - name: local-win
    platform: windows
    transport: local
    address: localhost
    tags: [local, windows]
    enabled: true

  - name: prod-web-1
    platform: linux
    transport: ssh
    address: 192.168.1.20
    user: ubuntu
    port: 22
    tags: [linux, web, prod]
    enabled: true
```

## Current Scope

What works now:

- terminal command `cody`
- interactive shell
- visible planning and execution phases
- local Ollama planner
- model switching from the Ollama model list
- inventory-aware host selection
- permission levels: `safe`, `elevated`, `full`
- policy-based approval gates
- automatic backup snapshots before `full` runs
- recent run history inspection
- local Windows execution
- SSH executor for Linux hosts
- WinRM executor path for Windows hosts
- run logs saved to disk
- workspace memo persistence for lightweight local memory such as Cody's assigned name

What is not done yet:

- credential vaulting
- rollback workflows
- parallel fleet execution
- streaming token-by-token planner output
- policy engine and approvals
- rich persistent memory/state across orchestrations
- service discovery

This is now a valid base to build the wider orchestrator on top of.
