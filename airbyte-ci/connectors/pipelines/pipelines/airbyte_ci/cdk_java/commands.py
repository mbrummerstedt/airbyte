#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import os
from pathlib import Path
from typing import List, Optional, Set, Tuple

import asyncclick as click
from connector_ops.utils import ConnectorLanguage, SupportLevelEnum, get_all_connectors_in_repo  # type: ignore
from pipelines import main_logger
from pipelines.cli.click_decorators import click_append_to_context_object, click_ignore_unused_kwargs, click_merge_args_into_context_obj
from pipelines.cli.lazy_group import LazyGroup
from pipelines.helpers.connectors.modifed import ConnectorWithModifiedFiles, get_connector_modified_files, get_modified_connectors
from pipelines.helpers.git import get_modified_files
from pipelines.helpers.utils import transform_strs_to_paths

ALL_CONNECTORS = get_all_connectors_in_repo()


def log_selected_connectors(selected_connectors_with_modified_files: List[ConnectorWithModifiedFiles]) -> None:
    if selected_connectors_with_modified_files:
        selected_connectors_names = [c.technical_name for c in selected_connectors_with_modified_files]
        main_logger.info(f"Will run on the following {len(selected_connectors_names)} connectors: {', '.join(selected_connectors_names)}.")
    else:
        main_logger.info("No connectors to run.")

def get_selected_connectors_with_modified_files(
    selected_names: Tuple[str],
    selected_support_levels: Tuple[str],
    selected_languages: Tuple[str],
    modified: bool,
    metadata_changes_only: bool,
    with_changelog_entry_files: bool,
    metadata_query: str,
    modified_files: Set[Path],
    enable_dependency_scanning: bool = False,
) -> List[ConnectorWithModifiedFiles]:
    """Get the connectors that match the selected criteria.

    Args:
        selected_names (Tuple[str]): Selected connector names.
        selected_support_levels (Tuple[str]): Selected connector support levels.
        selected_languages (Tuple[str]): Selected connector languages.
        modified (bool): Whether to select the modified connectors.
        metadata_changes_only (bool): Whether to select only the connectors with metadata changes.
        with_changelog_entry_files (bool): Whether to select the connectors with files in .changelog_entries
        modified_files (Set[Path]): The modified files.
        enable_dependency_scanning (bool): Whether to enable the dependency scanning.
    Returns:
        List[ConnectorWithModifiedFiles]: The connectors that match the selected criteria.
    """

    if metadata_changes_only and not modified:
        main_logger.info("--metadata-changes-only overrides --modified")
        modified = True

    selected_modified_connectors = (
        get_modified_connectors(modified_files, ALL_CONNECTORS, enable_dependency_scanning) if modified else set()
    )
    selected_connectors_by_name = {c for c in ALL_CONNECTORS if c.technical_name in selected_names}
    selected_connectors_by_support_level = {connector for connector in ALL_CONNECTORS if connector.support_level in selected_support_levels}
    selected_connectors_by_language = {connector for connector in ALL_CONNECTORS if connector.language in selected_languages}
    selected_connectors_by_query = (
        {connector for connector in ALL_CONNECTORS if connector.metadata_query_match(metadata_query)} if metadata_query else set()
    )
    selected_connectors_by_changelog_entry_files = {c for c in ALL_CONNECTORS if c.changelog_entry_files} if with_changelog_entry_files else set()

    non_empty_connector_sets = [
        connector_set
        for connector_set in [
            selected_connectors_by_name,
            selected_connectors_by_support_level,
            selected_connectors_by_language,
            selected_connectors_by_query,
            selected_modified_connectors,
            selected_connectors_by_changelog_entry_files
        ]
        if connector_set
    ]
    # The selected connectors are the intersection of the selected connectors by name, support_level, language, simpleeval query and modified.
    selected_connectors = set.intersection(*non_empty_connector_sets) if non_empty_connector_sets else set()

    selected_connectors_with_modified_files = []
    for connector in selected_connectors:
        connector_with_modified_files = ConnectorWithModifiedFiles(
            relative_connector_path=connector.relative_connector_path,
            modified_files=get_connector_modified_files(connector, modified_files),
        )
        if not metadata_changes_only:
            selected_connectors_with_modified_files.append(connector_with_modified_files)
        else:
            if connector_with_modified_files.has_metadata_change:
                selected_connectors_with_modified_files.append(connector_with_modified_files)
    return selected_connectors_with_modified_files


def validate_environment(is_local: bool) -> None:
    """Check if the required environment variables exist."""
    if is_local:
        if not Path(".git").is_dir():
            raise click.UsageError("You need to run this command from the repository root.")
    else:
        required_env_vars_for_ci = [
            "GCP_GSM_CREDENTIALS",
            "CI_REPORT_BUCKET_NAME",
            "CI_GITHUB_ACCESS_TOKEN",
            "DOCKER_HUB_USERNAME",
            "DOCKER_HUB_PASSWORD",
        ]
        for required_env_var in required_env_vars_for_ci:
            if os.getenv(required_env_var) is None:
                raise click.UsageError(f"When running in a CI context a {required_env_var} environment variable must be set.")


def should_use_remote_secrets(use_remote_secrets: Optional[bool]) -> bool:
    """Check if the connector secrets should be loaded from Airbyte GSM or from the local secrets directory.

    Args:
        use_remote_secrets (Optional[bool]): Whether to use remote connector secrets or local connector secrets according to user inputs.

    Raises:
        click.UsageError: If the --use-remote-secrets flag was provided but no GCP_GSM_CREDENTIALS environment variable was found.

    Returns:
        bool: Whether to use remote connector secrets (True) or local connector secrets (False).
    """
    gcp_gsm_credentials_is_set = bool(os.getenv("GCP_GSM_CREDENTIALS"))
    if use_remote_secrets is None:
        if gcp_gsm_credentials_is_set:
            main_logger.info("GCP_GSM_CREDENTIALS environment variable found, using remote connector secrets.")
            return True
        else:
            main_logger.info("No GCP_GSM_CREDENTIALS environment variable found, using local connector secrets.")
            return False
    if use_remote_secrets:
        if gcp_gsm_credentials_is_set:
            main_logger.info("GCP_GSM_CREDENTIALS environment variable found, using remote connector secrets.")
            return True
        else:
            raise click.UsageError("The --use-remote-secrets flag was provided but no GCP_GSM_CREDENTIALS environment variable was found.")
    else:
        main_logger.info("Using local connector secrets as the --use-local-secrets flag was provided")
        return False


@click.group(
    cls=LazyGroup,
    help="Commands related to connectors and connector acceptance tests.",
    lazy_subcommands={
        "bump_version": "pipelines.airbyte_ci.cdk_java.bump_version.commands.bump_version",
    },
)
@click_merge_args_into_context_obj
@click_append_to_context_object("use_remote_secrets", lambda ctx: should_use_remote_secrets(ctx.obj["use_remote_secrets"]))
@click.pass_context
@click_ignore_unused_kwargs
async def connectors(
    ctx: click.Context,
) -> None:
    """Group all the connectors-ci command."""
    validate_environment(ctx.obj["is_local"])

    modified_files = []
    if ctx.obj["modified"] or ctx.obj["metadata_changes_only"]:
        modified_files = transform_strs_to_paths(
            await get_modified_files(
                ctx.obj["git_branch"],
                ctx.obj["git_revision"],
                ctx.obj["diffed_branch"],
                ctx.obj["is_local"],
                ctx.obj["ci_context"],
            )
        )

    ctx.obj["selected_connectors_with_modified_files"] = get_selected_connectors_with_modified_files(
        ctx.obj["names"],
        ctx.obj["support_levels"],
        ctx.obj["languages"],
        ctx.obj["modified"],
        ctx.obj["metadata_changes_only"],
        ctx.obj["with_changelog_entry_files"],
        ctx.obj["metadata_query"],
        set(modified_files),
        ctx.obj["enable_dependency_scanning"],
    )
    log_selected_connectors(ctx.obj["selected_connectors_with_modified_files"])
