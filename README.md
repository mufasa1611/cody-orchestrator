# Codex

`codex` is an Autonomous Infrastructure Orchestrator shell powered by local Ollama AI models. It is designed to manage, inspect, and modify infrastructure across Windows and Linux fleets.

Created by Mufasa (M. Farid).

## 🚀 Key Features

- **Autonomous Agentic Loop**: Codex doesn't just run commands; it analyzes results and re-plans up to 3 times if a step fails to find a solution.
- **Surgical File Editing**: Precision code modifications using exact string replacement instead of risky overwrites.
- **Rich Persistent Memory**: Powered by a long-term SQLite database, Codex remembers every run, step, and success to provide better context for future tasks.
- **Service Discovery**: Built-in network scanning with TTL-based OS fingerprinting to automatically map your infrastructure.
- **Web Research**: Integrated web search (via `ddgs`) for troubleshooting errors and finding documentation.
- **Parallel Fleet Execution**: Run the same maintenance or inspection tasks across multiple hosts simultaneously.
- **Live Streaming**: Real-time STDOUT/STDERR streaming for full backend transparency.
- **Safety Gates**: Three-tier permission system (`safe`, `elevated`, `full`) with automatic backup snapshots for risky runs.

## 🛠️ Architecture

The codebase follows a structured runtime flow:

```text
Conversation Model (LLM)
        ↓
Intent Parser (Local + LLM)
        ↓
Policy Gate (Permissions & Approvals)
        ↓
Task Router (Deterministic + Planner Agent)
   ↙             ↘
Deterministic    Planner Agent (LLM)
  Handlers
        ↓
Execution Layer (Local, SSH, WinRM)
        ↓
Long-term Memory (SQLite) / Backups
```

## 📦 Installation

The easiest way to install Codex is using the automated installer:

1.  **Clone the Repo**:
    ```powershell
    git clone https://github.com/mufasa1611/cody-orchestrator.git
    cd cody-orchestrator
    ```
2.  **Run the Installer**:
    ```powershell
    .\install-codex.bat
    ```
    This will set up the virtual environment, install dependencies, and create a global `codex` command for you.

## ⌨️ First Use

Simply type `codex` to start the interactive shell. On your first run, a **Setup Wizard** will guide you through:
- Checking if Ollama is running (and offer to start it for you).
- Detecting your hardware (VRAM/CPU) to suggest the best AI model.
- Automatically downloading the required model if it's missing.

## 🕹️ Interactive Shell

Inside the shell, you can use natural language or special `/` commands. 
*Pro-tip: Type `/` to see a searchable menu!*

- **Natural Language**: `search my c: for test.txt`, `discover hosts on my network`, `clean up temp files`.
- `/status`: Show current model, permissions, and database paths.
- `/model`: Open the interactive model selector.
- `/permissions`: Switch between safe, elevated, and full modes.
- `/runs`: List execution history or show the latest run summary.
- `/doctor`: Run a full system diagnostic.

## 🛡️ License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
