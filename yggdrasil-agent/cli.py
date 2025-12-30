#!/usr/bin/env python3
"""
ygg - Yggdrasil Agent CLI

Commands:
  sync      Scan Obsidian for #agent tasks, create Beads
  status    Check system health (agents, LLMs, pending tasks)
  run       Process one ready task
  loop      Run continuous task processing
"""

import sys
import click
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from obsidian_parser import parse_obsidian_tasks
from beads_sync import sync_obsidian_to_beads, get_sync_state
from agent import YggdrasilAgent


@click.group()
@click.version_option()
def cli():
    """Yggdrasil - Multi-agent task processor"""
    pass


@cli.command()
@click.option('--vault', type=click.Path(exists=True), default=None, help='Obsidian vault path')
@click.option('--beads', type=click.Path(exists=True), default=None, help='Beads directory path')
@click.option('--dry-run', is_flag=True, help='Show what would sync without creating Beads')
def sync(vault, beads, dry_run):
    """Scan Obsidian for #agent tasks and create Beads"""
    
    # Find vault if not specified
    if not vault:
        vault = Path.home() / 'obsidian-vault'
    vault = Path(vault)
    
    if not (vault / '2-Projects').exists():
        click.echo(f"Error: Obsidian vault not found at {vault}", err=True)
        sys.exit(1)
    
    # Find beads if not specified
    if not beads:
        beads = Path.home() / 'homelab-config/yggdrasil-beads'
    beads = Path(beads)
    
    if not (beads / '.beads/issues.jsonl').exists():
        click.echo(f"Error: Beads not found at {beads}", err=True)
        sys.exit(1)
    
    # Parse Obsidian tasks
    click.echo(f"Scanning {vault}...")
    tasks = parse_obsidian_tasks(vault)
    click.echo(f"Found {len(tasks)} #agent tasks")
    
    if dry_run:
        for task in tasks:
            click.echo(f"  - {task['description']} ({task['type']}, {task['priority']})")
        click.echo("\nDry run - no Beads created")
        return
    
    # Sync to Beads
    created = sync_obsidian_to_beads(tasks, beads)
    click.echo(f"✓ Created {created} new Beads")


@cli.command()
def status():
    """Check system health"""
    from beads_sync import get_beads_stats
    from llm_router import check_llm_health
    from pathlib import Path
    import json
    
    click.echo("=== Yggdrasil Status ===\n")
    
    # Beads
    stats = get_beads_stats()
    click.echo(f"Beads: {stats['open']} open, {stats['in_progress']} processing, {stats['closed']} completed")
    
    # In-progress tasks
    if stats['in_progress'] > 0:
        click.echo("\nProcessing Tasks:")
        
        # Find Beads directory
        beads_path = None
        for path in [Path('/beads'), Path.home() / 'homelab-config/yggdrasil-beads']:
            if (path / '.beads/issues.jsonl').exists():
                beads_path = path
                break
        
        if beads_path:
            in_progress = []
            try:
                with open(beads_path / '.beads/issues.jsonl') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            if data.get('status') == 'in_progress':
                                in_progress.append(data)
                        except json.JSONDecodeError:
                            # Skip corrupted lines
                            pass
            except Exception as e:
                click.echo(f"  Error reading tasks: {e}", err=True)
                in_progress = []
            
            if in_progress:
                for task in in_progress:
                    task_id = task.get('id', 'unknown')
                    title = task.get('title', '')[:40]
                    click.echo(f"  • {task_id}: {title}")
            elif stats['in_progress'] > 0:
                click.echo(f"  ({stats['in_progress']} tasks in progress - could not read details)")
    
    # LLM Health
    click.echo("\nLLM Hosts:")
    health = check_llm_health()
    for name, info in health.items():
        status_str = "✓" if info['healthy'] else "✗"
        click.echo(f"  {status_str} {name}: {info['status']} ({info.get('model', 'n/a')})")
    
    click.echo()


@cli.command()
@click.option('--beads', type=click.Path(exists=True), default=None, help='Beads directory')
def run(beads):
    """Process one ready task"""
    agent = YggdrasilAgent()
    if agent.run_once():
        click.echo("✓ Task processed")
    else:
        click.echo("No ready tasks")


@cli.command()
@click.option('--interval', type=int, default=30, help='Poll interval (seconds)')
@click.option('--async', 'use_async', is_flag=True, help='Use async dispatcher (better concurrency)')
def loop(interval, use_async):
    """Continuously process tasks (dispatches to all available agents)"""
    
    if use_async:
        # Use improved async dispatcher with per-host concurrency
        import asyncio
        from async_dispatcher import AsyncYggdrasilAgent
        
        click.echo(f"Starting async dispatcher (interval: {interval}s)...")
        click.echo("Mode: Per-host concurrency limits")
        
        try:
            agent = AsyncYggdrasilAgent()
            asyncio.run(agent.run_loop(poll_interval=interval))
        except KeyboardInterrupt:
            click.echo("\n✓ Async dispatcher stopped")
    else:
        # Use legacy thread-based dispatcher
        agent = YggdrasilAgent()
        click.echo(f"Starting dispatcher (interval: {interval}s)...")
        click.echo("Mode: One task per agent type")
        
        try:
            agent.run_loop(poll_interval=interval)
        except KeyboardInterrupt:
            click.echo("\n✓ Agent stopped")


if __name__ == '__main__':
    cli()
