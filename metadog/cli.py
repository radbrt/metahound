import logging
import click
from metadog.cli_functions import init_fn, scan_fn, warnings_fn, backend_fn, push_fn, token_set_fn, url_set_fn, status_fn


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose (debug) logging')
@click.pass_context
def metadog(ctx, verbose):
    """Main metadog command entrypoint"""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format='%(name)s %(levelname)s: %(message)s')


@metadog.command()
@click.argument('foldername')
def init(foldername: str):
    """
    Initialize a new metadog project in the specified folder
    """
    init_fn(foldername)


@metadog.command()
def backend():
    backend_fn()


@metadog.command()
@click.option('--select', '-s', help='Select sources to scan')
@click.option('--no-stats', help='Omit generating table statistics', is_flag=True)
def scan(select, no_stats):
    """
    Run a scan based on the configuration file
    """
    scan_fn(select, no_stats)


@metadog.command()
@click.option('--algorithm', '-a', help='Algorithm to use for outlier detection. zindex or prophet', default='zindex')
@click.option('--threshold', '-t', type=float, default=None, help='Z-score threshold override (default: 3.0 or from spec)')
def warnings(algorithm, threshold):
    """
    Analyze database statistics and print warnings based on predicted values
    """
    warnings_fn(algorithm, threshold=threshold)


@metadog.command()
@click.option('--api-url', default=None, help='Metadog server URL (overrides METADOG_API_URL)')
@click.option('--token', default=None, help='API token (overrides METADOG_API_TOKEN)')
def push(api_url, token):
    """Push local scan data to the Metadog server."""
    push_fn(api_url=api_url, api_token=token)


@metadog.command()
def status():
    """Print a summary of sources and recent scans stored in the backend."""
    status_fn()


@metadog.group()
def config():
    """Manage local Metadog configuration."""
    pass


@config.command('set-token')
@click.argument('token')
def set_token(token):
    """Save an API token to the local .env file."""
    token_set_fn(token)


@config.command('set-url')
@click.argument('api_url')
def set_url(api_url):
    """Save the Metadog server URL to the local .env file."""
    url_set_fn(api_url)


@metadog.command()
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
