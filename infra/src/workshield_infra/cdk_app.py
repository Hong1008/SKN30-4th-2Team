"""WorkShield AWS CDK 애플리케이션 진입점."""

from pathlib import Path

from aws_cdk import App, Environment, Tags

from workshield_infra.config import DeploymentConfig
from workshield_infra.stacks.access import AccessStack
from workshield_infra.stacks.foundation import FoundationStack
from workshield_infra.stacks.service import ServiceStack


app = App()
config_path = Path(app.node.try_get_context("config") or "config/prod.example.json")
if not config_path.is_absolute():
    config_path = Path(__file__).resolve().parents[2] / config_path
config = DeploymentConfig.from_file(config_path.resolve())
environment = Environment(account=config.aws_account_id, region=config.aws_region)
access = AccessStack(app, "WorkShieldAccess", config=config, env=environment)
foundation = FoundationStack(app, "WorkShieldFoundation", config=config, env=environment)
ServiceStack(app, "WorkShieldService", config=config, access=access, foundation=foundation, env=environment)
Tags.of(app).add("Project", "WorkShield")
Tags.of(app).add("Environment", config.environment)
Tags.of(app).add("ManagedBy", "workshield-infra")
app.synth()
