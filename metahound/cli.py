import logging
import click
from metahound.cli_functions import (
    init_fn,
    scan_fn,
    warnings_fn,
    backend_fn,
    push_fn,
    token_set_fn,
    url_set_fn,
    status_fn,
    changes_fn,
)


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose (debug) logging')
@click.pass_context
def metahound(ctx, verbose):
    """Main metahound command entrypoint"""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format='%(name)s %(levelname)s: %(message)s')


@metahound.command()
@click.argument('foldername')
def init(foldername: str):
    """
    Initialize a new metahound project in the specified folder
    """
    init_fn(foldername)


@metahound.command()
def backend():
    backend_fn()


@metahound.command()
@click.option('--select', '-s', help='Select sources to scan')
@click.option('--no-stats', help='Omit generating table statistics', is_flag=True)
def scan(select, no_stats):
    """
    Run a scan based on the configuration file
    """
    scan_fn(select, no_stats)


@metahound.command()
@click.option('--algorithm', '-a', help='Algorithm to use for outlier detection. zindex or prophet', default='zindex')
@click.option('--threshold', '-t', type=float, default=None, help='Z-score threshold override (default: 3.0 or from spec)')
def warnings(algorithm, threshold):
    """
    Analyze database statistics and print warnings based on predicted values
    """
    warnings_fn(algorithm, threshold=threshold)


@metahound.command()
@click.option('--api-url', default=None, help='Metahound server URL (overrides METAHOUND_API_URL)')
@click.option('--token', default=None, help='API token (overrides METAHOUND_API_TOKEN)')
def push(api_url, token):
    """Push local scan data to the Metahound server."""
    push_fn(api_url=api_url, api_token=token)


@metahound.command()
@click.option('--since', default=None, help='Show changes recorded at or after this ISO timestamp (default: most recent scan per source)')
@click.option('--fail-on', type=click.Choice(['breaking', 'any']), default=None,
              help='Exit non-zero if matching changes exist — use to gate ingest pipelines')
def changes(since, fail_on):
    """Show schema changes detected by scans (column/table added, removed, type changed)."""
    changes_fn(since, fail_on)


@metahound.command()
def status():
    """Print a summary of sources and recent scans stored in the backend."""
    status_fn()


@metahound.group()
def config():
    """Manage local Metahound configuration."""
    pass


@config.command('set-token')
@click.argument('token')
def set_token(token):
    """Save an API token to the local .env file."""
    token_set_fn(token)


@config.command('set-url')
@click.argument('api_url')
def set_url(api_url):
    """Save the Metahound server URL to the local .env file."""
    url_set_fn(api_url)


@metahound.command()
def hello():
    """
    Print a friendly greeting
    """
    print(
        r"""
           _____  ___________________________  ________   ________    ________     / \__
          /     \ \_   _____/\__    ___/  _  \ \______ \  \_____  \  /  _____/    (    @\__
         /  \ /  \ |    __)_   |    | /  /_\  \ |    |  \  /   |   \/   \  ___    /         O
        /    Y    \|        \  |    |/    |    \|    `   \/    |    \    \_\  \   /   (_____/
        \____|__  /_______  /  |____|\____|__  /_______  /\_______  /\______  /   /_____/  U
                \/        \/                 \/        \/         \/        \/
        """
    )
