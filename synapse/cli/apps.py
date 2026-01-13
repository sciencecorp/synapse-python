"""CLI commands for managing Synapse applications."""

from synapse.cli.build import build_cmd
from synapse.cli.deploy import deploy_cmd
from synapse.cli.rpc import list_apps


def add_commands(subparsers):
    """Add the apps command group to the CLI."""
    apps_parser = subparsers.add_parser("apps", help="Manage applications on a Synapse device")
    apps_subparsers = apps_parser.add_subparsers(title="App Commands")

    # build subcommand
    build_parser = apps_subparsers.add_parser(
        "build",
        help="Cross-compile and package an application into a .deb without deploying",
    )
    build_parser.add_argument(
        "app_dir",
        nargs="?",
        default=".",
        help="Path to the application directory (defaults to current working directory)",
    )
    build_parser.add_argument(
        "--skip-build",
        action="store_true",
        default=False,
        help="Skip compilation phase; assume the binary already exists and only build the .deb package.",
    )
    build_parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Clean build directories and force a complete rebuild from scratch.",
    )
    build_parser.set_defaults(func=build_cmd)

    # deploy subcommand
    deploy_parser = apps_subparsers.add_parser(
        "deploy", help="Deploy an application to a Synapse device"
    )
    deploy_parser.add_argument(
        "app_dir", nargs="?", default=".", help="Path to the application directory"
    )
    deploy_parser.add_argument(
        "--package",
        "-p",
        help="Path to a pre-built .deb to deploy (skips local build and package steps)",
        type=str,
        default=None,
    )
    deploy_parser.set_defaults(func=deploy_cmd)

    # list subcommand
    list_parser = apps_subparsers.add_parser(
        "list", help="List installed applications on the device"
    )
    list_parser.set_defaults(func=list_apps)
