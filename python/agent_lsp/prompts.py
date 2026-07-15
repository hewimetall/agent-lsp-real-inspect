"""Important MCP prompts (FastMCP ``@mcp.prompt``) — not an HTTP /prompt route.

Only high-traffic scout flows: onboard, explore, impact, safe_edit, verify,
and mirror (local bare when catalog present). Composite ``refactor`` omitted.
"""

from __future__ import annotations

from typing import Any


def register_prompts(mcp: Any) -> None:
    """Attach scout prompts to a FastMCP server instance."""

    @mcp.prompt(
        name="onboard",
        title="LSP onboard",
        description=(
            "Open sources into a warm scout session: import → checkout → "
            "optional deps → ensure_runtime → warm_index."
        ),
        tags={"scout", "onboard"},
    )
    def onboard(
        project_id: str,
        source: str,
        language: str = "python",
        language_version: str = "3.12",
        ref_name: str = "HEAD",
        packages: str = "",
        apt_packages: str = "",
        ensure_runtime: str = "yes",
        warm_index: str = "yes",
        notes: str = "",
    ) -> str:
        """Build the onboard checklist for the agent."""
        return "\n".join(
            [
                "Run agent-lsp onboard (MCP tools; long ops wait with progress):",
                f"- project_id: {project_id}",
                f"- source: {source}  # git URL | local path | mirror:<id>",
                f"- ref_name: {ref_name}",
                f"- language: {language}",
                f"- language_version: {language_version}",
                f"- packages: {packages or '(none)'}",
                f"- apt_packages: {apt_packages or '(none)'}",
                f"- ensure_runtime: {ensure_runtime}",
                f"- warm_index: {warm_index}",
                f"- notes: {notes or '(none)'}",
                "",
                "Steps:",
                "1. create_session",
                "2. import_project(project_id, source)",
                "3. checkout_workspace(session_id, project_id, ref_name)",
                "4. if packages/apt_packages: install_workspace_deps / install_apt_packages",
                "5. if ensure_runtime=yes: ensure_runtime(session_id, language, language_version)",
                "6. if warm_index=yes: warm_index(session_id)",
                "7. then scout (explore_symbol / blast_radius)",
                "Skill: skills/lsp-onboard/SKILL.md",
            ]
        )

    @mcp.prompt(
        name="mirror",
        title="LSP mirror onboard",
        description=(
            "Sync local git mirrors by hand on the host, then onboard via "
            "source=mirror:<id> (when mirrors catalog is deployed)."
        ),
        tags={"scout", "mirror"},
    )
    def mirror(
        mirror_ids: str,
        language: str = "python",
        language_version: str = "3.12",
        sync_now: str = "yes",
        ensure_runtime: str = "yes",
        warm_index: str = "yes",
        notes: str = "",
    ) -> str:
        """Build the mirror onboard checklist."""
        return "\n".join(
            [
                "Run agent-lsp mirror onboard:",
                f"- mirror_ids: {mirror_ids}",
                f"- sync_now: {sync_now}",
                f"- language: {language}",
                f"- language_version: {language_version}",
                f"- ensure_runtime: {ensure_runtime}",
                f"- warm_index: {warm_index}",
                f"- notes: {notes or '(none)'}",
                "",
                "Steps:",
                "1. If sync_now=yes: on the agent-lsp HOST run mirror-sync for <ids>",
                "   (see infra/mirrors/mirrors.toml when present; never auto-clone in MCP).",
                "2. create_session",
                "3. For each id: import_project(project_id=<id>, source='mirror:<id>')",
                "4. checkout_workspace(session_id, project_id=<first id>)",
                "5. if ensure_runtime=yes: ensure_runtime(...)",
                "6. if warm_index=yes: warm_index(...)",
                "Skill: skills/lsp-mirror/SKILL.md (when present)",
            ]
        )

    @mcp.prompt(
        name="explore",
        title="LSP explore symbol",
        description="Hover + definition + references via explore_symbol (warm session required).",
        tags={"scout", "explore"},
    )
    def explore(
        file_path: str,
        line: int,
        column: int,
        session_id: str = "current",
        follow_blast: str = "no",
        notes: str = "",
    ) -> str:
        return "\n".join(
            [
                "Run agent-lsp explore:",
                f"- session_id: {session_id}",
                f"- file_path: {file_path}",
                f"- line: {line}",
                f"- column: {column}",
                f"- follow_blast: {follow_blast}",
                f"- notes: {notes or '(none)'}",
                "",
                "Steps:",
                "1. Require warm index (warm_index if needed).",
                "2. explore_symbol(session_id, file_path, line, column)",
                "3. if follow_blast=yes: blast_radius(session_id, [file_path])",
                "Skill: skills/lsp-explore/SKILL.md",
            ]
        )

    @mcp.prompt(
        name="impact",
        title="LSP blast impact",
        description="blast_radius on changed files before editing.",
        tags={"scout", "impact"},
    )
    def impact(
        changed_files: str,
        session_id: str = "current",
        include_transitive: str = "no",
        halt_if_large: str = "yes",
        notes: str = "",
    ) -> str:
        return "\n".join(
            [
                "Run agent-lsp impact (blast_radius):",
                f"- session_id: {session_id}",
                f"- changed_files: {changed_files}",
                f"- include_transitive: {include_transitive}",
                f"- halt_if_large: {halt_if_large}",
                f"- notes: {notes or '(none)'}",
                "",
                "Steps:",
                "1. Require warm index.",
                "2. blast_radius(session_id, changed_files.split(','), include_transitive=...)",
                "3. Report non-test vs test callers; if halt_if_large=yes and blast is huge, stop.",
                "Skill: skills/lsp-impact/SKILL.md",
            ]
        )

    @mcp.prompt(
        name="safe_edit",
        title="LSP safe edit",
        description="Blast-gate then edit the active worktree.",
        tags={"scout", "edit"},
    )
    def safe_edit(
        file_path: str,
        intent: str,
        session_id: str = "current",
        run_blast: str = "yes",
        commit: str = "no",
        commit_message: str = "",
        notes: str = "",
    ) -> str:
        return "\n".join(
            [
                "Run agent-lsp safe-edit:",
                f"- session_id: {session_id}",
                f"- file_path: {file_path}",
                f"- intent: {intent}",
                f"- run_blast: {run_blast}",
                f"- commit: {commit}",
                f"- commit_message: {commit_message or '(n/a)'}",
                f"- notes: {notes or '(none)'}",
                "",
                "Steps:",
                "1. if run_blast=yes: blast_radius on file_path; halt if unsafe.",
                "2. Edit in the active worktree only.",
                "3. Re-check explore_symbol / find_references.",
                "4. if commit=yes: commit_workspace(session_id, message=...)",
                "Skill: skills/lsp-safe-edit/SKILL.md",
            ]
        )

    @mcp.prompt(
        name="verify",
        title="LSP verify after edits",
        description="Re-warm if needed, re-blast touched files, spot-check symbols.",
        tags={"scout", "verify"},
    )
    def verify(
        touched_files: str,
        session_id: str = "current",
        rewarm: str = "no",
        spot_check: str = "",
        notes: str = "",
    ) -> str:
        return "\n".join(
            [
                "Run agent-lsp verify:",
                f"- session_id: {session_id}",
                f"- touched_files: {touched_files}",
                f"- rewarm: {rewarm}",
                f"- spot_check: {spot_check or '(none)'}",
                f"- notes: {notes or '(none)'}",
                "",
                "Steps:",
                "1. if rewarm=yes or index cold: warm_index(session_id)",
                "2. blast_radius(session_id, touched_files)",
                "3. Spot-check explore_symbol / find_references on spot_check entries",
                "Skill: skills/lsp-verify/SKILL.md",
            ]
        )
