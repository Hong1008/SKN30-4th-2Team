from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from workshield_infra import tasks


def test_github_configure_fails_before_loading_config_when_gh_is_logged_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        tasks.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            returncode=1,
            stdout="",
            stderr="not logged in",
        ),
    )
    monkeypatch.setattr(
        tasks,
        "_load",
        lambda *args, **kwargs: pytest.fail("로그인 확인 전에 설정을 읽었습니다."),
    )

    with pytest.raises(RuntimeError, match="gh auth login"):
        tasks.github_configure("profile", "prod", "production")


def test_github_configure_uses_authenticated_gh_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        github_environment="production",
        github_organization="example",
        github_repository="repository",
        ghcr_owner="example",
        aws_region="ap-northeast-2",
    )
    outputs = {
        ("WorkShieldAccess", "GitHubDeployRoleArn"): "role-arn",
        ("WorkShieldService", "DeployDocumentName"): "deploy-document",
        ("WorkShieldService", "WebBucketName"): "web-bucket",
        ("WorkShieldService", "CloudFrontDistributionId"): "distribution",
    }
    aws = SimpleNamespace(
        stack_output=lambda stack, output: outputs[(stack, output)],
    )
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        stdout = "AWS_REGION\n" if "--paginate" in command else ""
        return subprocess.CompletedProcess(command, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(tasks.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(tasks.subprocess, "run", run)
    monkeypatch.setattr(
        tasks,
        "_load",
        lambda *args, **kwargs: (config, {}, None, None, None),
    )
    monkeypatch.setattr(tasks, "_providers", lambda *args, **kwargs: (aws, None))
    monkeypatch.setattr(tasks, "_assert_identity", lambda *args: None)

    tasks.github_configure("profile", "prod", "production")

    assert commands[0] == ["gh", "auth", "status", "--hostname", "github.com"]
    api_commands = commands[1:]
    assert api_commands
    assert all(command[:2] == ["gh", "api"] for command in api_commands)
    assert not any(
        "Authorization" in argument or "Bearer" in argument
        for command in commands
        for argument in command
    )
    assert any("--method" in command and "PATCH" in command for command in api_commands)
    assert any("--method" in command and "POST" in command for command in api_commands)
