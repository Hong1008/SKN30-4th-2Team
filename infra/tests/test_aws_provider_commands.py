from pathlib import Path
from types import SimpleNamespace

from workshield_infra.providers.aws import AwsProvider


def test_bootstrap_uses_windows_npm_command(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    provider = AwsProvider(
        SimpleNamespace(aws_account_id="111122223333", aws_region="ap-northeast-2"),
        profile="workshield-session",
        infra_root=tmp_path,
    )
    monkeypatch.setattr("workshield_infra.providers.aws.os.name", "nt")
    monkeypatch.setattr(
        "workshield_infra.providers.aws.subprocess.run",
        lambda command, **_kwargs: calls.append(command),
    )

    provider.bootstrap()

    assert calls == [
        [
            "npm.cmd",
            "exec",
            "cdk",
            "--",
            "bootstrap",
            "aws://111122223333/ap-northeast-2",
            "--profile",
            "workshield-session",
        ]
    ]
