"""
Contract Deployment Script for FaceMatchRegistry.
Deploys to Polygon Amoy Testnet (Chain ID 80002) or Local EVM.
Updates .env with the new CONTRACT_ADDRESS.
"""

import argparse
import logging
import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from pipeline.chain.client import BlockchainClient

load_dotenv()
console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def update_env_file(contract_address: str):
    """Updates CONTRACT_ADDRESS in local .env file."""
    env_path = ".env"
    if not os.path.exists(env_path):
        if os.path.exists(".env.example"):
            with open(".env.example", "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = ""
    else:
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

    lines = content.splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("CONTRACT_ADDRESS="):
            new_lines.append(f"CONTRACT_ADDRESS={contract_address}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"CONTRACT_ADDRESS={contract_address}")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines) + "\n")

    console.print(f"[green]Saved CONTRACT_ADDRESS to {env_path}[/green]")


def main():
    parser = argparse.ArgumentParser(description="Deploy FaceMatchRegistry Smart Contract")
    parser.add_argument("--local", action="store_true", help="Deploy to local in-memory EVM chain")
    parser.add_argument("--private-key", type=str, help="Custom private key override")
    args = parser.parse_args()

    use_local = args.local or os.getenv("USE_LOCAL_CHAIN", "false").lower() == "true"
    console.print(
        Panel(
            f"Deploying [bold cyan]FaceMatchRegistry[/bold cyan] (Solidity 0.8.20)\n"
            f"Target: {'[yellow]Local In-Memory EVM[/yellow]' if use_local else '[cyan]Polygon Amoy Testnet[/cyan]'}",
            title="Smart Contract Deployment",
            border_style="cyan",
        )
    )

    client = BlockchainClient(use_local_chain=use_local)
    diag = client.get_diagnostics()

    if not use_local:
        console.print(f"RPC Connected: [{'green' if diag['rpc_connected'] else 'red'}]{diag['rpc_connected']}[/{'green' if diag['rpc_connected'] else 'red'}] ({diag['active_rpc_url']})")
        console.print(f"Chain ID: [cyan]{diag['actual_chain_id']}[/cyan]")
        if diag["wallet"]["configured"]:
            console.print(f"Wallet: [cyan]{diag['wallet']['address']}[/cyan] (Balance: [bold]{diag['wallet']['balance_pol']:.4f} POL[/bold])")
        else:
            console.print(f"[yellow]Wallet Warning: {diag['wallet']['message']}[/yellow]")

    try:
        contract_addr, tx_hash = client.deploy_contract(private_key=args.private_key or "default" if use_local else None)
        console.print()
        console.print(f"[bold green]Contract Deployed Successfully![/bold green]")
        console.print(f"Contract Address: [bold cyan]{contract_addr}[/bold cyan]")
        console.print(f"Deployment Tx Hash: [dim]{tx_hash}[/dim]")

        if not use_local:
            update_env_file(contract_addr)
            console.print(f"Amoy Explorer: [blue]https://amoy.polygonscan.com/address/{contract_addr}[/blue]")

    except Exception as e:
        console.print()
        console.print(f"[bold red]Deployment Failed: {e}[/bold red]")
        if not use_local and ("insufficient" in str(e).lower() or "0.00" in str(e)):
            console.print("[yellow]Hint: Fund your wallet with testnet POL from:[/yellow]")
            console.print("  1. https://faucet.polygon.technology/")
            console.print("  2. https://www.alchemy.com/faucets/polygon-amoy")
            console.print("  3. https://faucets.chain.link/polygon-amoy")
        sys.exit(1)


if __name__ == "__main__":
    main()
