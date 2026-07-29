"""WorkShield AWS CDK 애플리케이션 진입점."""

from pathlib import Path

from aws_cdk import App, Environment, Tags

from stacks.config import DeploymentConfig
from stacks.foundation_stack import FoundationStack
from stacks.service_stack import ServiceStack


app = App()
config_path = Path(app.node.try_get_context("config") or "../config/prod.example.json")
if not config_path.is_absolute():
    config_path = Path(__file__).resolve().parent / config_path
config = DeploymentConfig.from_file(config_path.resolve())
environment = Environment(account=config.aws_account_id, region=config.aws_region)
foundation = FoundationStack(app, "WorkShieldFoundation", config=config, env=environment)
ServiceStack(app, "WorkShieldService", config=config, foundation=foundation, env=environment)
Tags.of(app).add("Project", "WorkShield")
Tags.of(app).add("Environment", "production")
app.synth()
