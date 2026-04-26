from __future__ import annotations

import os
import subprocess
import sys
import time
import requests

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

console = Console()

def check_ollama() -> bool:
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False

def find_ollama_exe() -> str | None:
    # 1. Check PATH
    try:
        result = subprocess.run(["where", "ollama"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.splitlines()[0].strip()
    except Exception:
        pass

    # 2. Check default Windows path
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        candidate = os.path.join(local_app_data, "Programs", "Ollama", "ollama.exe")
        if os.path.exists(candidate):
            return candidate

    return None

def start_ollama_automatically() -> bool:
    exe = find_ollama_exe()
    if not exe:
        return False

    console.print("[cyan]Starting Ollama server in background...[/cyan]")
    try:
        # Start in background without a visible window
        subprocess.Popen(
            [exe, "serve"],
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        # Give it a few seconds to boot
        for _ in range(10):
            time.sleep(1)
            if check_ollama():
                return True
    except Exception:
        pass
    return False

def get_installed_models() -> list[str]:

    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        if response.status_code == 200:
            data = response.json()
            return [m.get("name") for m in data.get("models", [])]
    except Exception:
        pass
    return []

def estimate_vram_gb() -> int:
    if os.name != "nt":
        return 0
    try:
        cmd = ["powershell.exe", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController | Measure-Object -Property AdapterRAM -Sum).Sum"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            bytes_vram = int(result.stdout.strip())
            return bytes_vram // (1024 ** 3)
    except Exception:
        pass
    return 0

def suggest_model(vram_gb: int) -> str:
    if vram_gb >= 8:
        return "gemma4:latest" # Assuming this is a powerful model
    elif vram_gb >= 4:
        return "gemma:2b"
    else:
        return "qwen2:0.5b"

def pull_model(model: str) -> bool:
    console.print(f"[cyan]Downloading model '{model}'... This may take a while.[/cyan]")
    try:
        process = subprocess.Popen(
            ["ollama", "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        for line in iter(process.stdout.readline, ""):
            print(line.strip())
        process.wait()
        return process.returncode == 0
    except FileNotFoundError:
        console.print("[red]Error: 'ollama' command not found in PATH.[/red]")
        return False
    except Exception as e:
        console.print(f"[red]Error pulling model: {e}[/red]")
        return False

def run_setup_wizard() -> str | None:
    console.print(Panel("[bold green]Welcome to Codex - First Run Setup[/bold green]", expand=False))
    
    # 1. Check Ollama
    # ... rest of logic
    console.print("Checking for Ollama...")
    if not check_ollama():
        console.print("[yellow]Ollama is not running.[/yellow]")
        if Confirm.ask("Would you like me to attempt to start the Ollama server for you automatically?"):
            if start_ollama_automatically():
                console.print("[bold green]✓ Ollama started successfully.[/bold green]")
            else:
                console.print("[bold red]❌ Failed to start Ollama automatically.[/bold red]")
                console.print("Please install Ollama from [blue]https://ollama.com[/blue] and ensure it's running (e.g., `ollama serve`).")
                while not check_ollama():
                    if Confirm.ask("Is Ollama running now? Try again?"):
                        continue
                    else:
                        return None
        else:
            console.print("Please ensure Ollama is running manually before proceeding.")
            while not check_ollama():
                if Confirm.ask("Is Ollama running now? Try again?"):
                    continue
                else:
                    return None
    console.print("[bold green]✓ Ollama is running.[/bold green]")

    # 2. Hardware check & suggestion
    console.print("Detecting hardware...")
    vram_gb = estimate_vram_gb()
    if vram_gb > 0:
        console.print(f"Detected roughly [cyan]{vram_gb} GB VRAM[/cyan].")
    else:
        console.print("Could not detect VRAM (or non-Windows OS).")
    
    suggested = suggest_model(vram_gb)
    installed = get_installed_models()
    
    if installed:
        console.print("\n[bold]Currently installed models:[/bold]")
        for m in installed:
            console.print(f"  - {m}")
    else:
        console.print("\n[yellow]No models currently installed in Ollama.[/yellow]")

    console.print(f"\nBased on your hardware, we suggest: [bold cyan]{suggested}[/bold cyan]")
    
    # 3. Model Selection
    choices = ["Use Suggested", "Type Custom Model"]
    if installed:
        choices.insert(0, "Select Installed Model")
    
    console.print("\n[bold]What would you like to do?[/bold]")
    for i, choice in enumerate(choices, 1):
        console.print(f"{i}. {choice}")
    
    selection = Prompt.ask("Enter your choice", choices=[str(i) for i in range(1, len(choices) + 1)], default="1")
    choice_text = choices[int(selection) - 1]
    
    selected_model = suggested
    
    if choice_text == "Select Installed Model":
        for i, m in enumerate(installed, 1):
            console.print(f"{i}. {m}")
        idx = Prompt.ask("Select model number", choices=[str(i) for i in range(1, len(installed) + 1)], default="1")
        selected_model = installed[int(idx) - 1]
    elif choice_text == "Type Custom Model":
        selected_model = Prompt.ask("Enter model name (e.g., llama3, mistral, phi3)")
        
    # 4. Pull if needed
    if selected_model not in installed:
        if Confirm.ask(f"Model '{selected_model}' is not installed. Download it now?"):
            success = pull_model(selected_model)
            if not success:
                console.print("[red]Failed to pull model. Using default config.[/red]")
                return None
        else:
            console.print("[yellow]Skipping download. You must download it manually before using Codex.[/yellow]")

    console.print(f"\n[bold green]Setup Complete! Codex will use '{selected_model}'.[/bold green]")
    return selected_model
