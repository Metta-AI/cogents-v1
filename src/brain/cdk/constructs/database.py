"""Aurora Serverless v2 database construct (no custom VPC)."""

from __future__ import annotations

from aws_cdk import RemovalPolicy
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from constructs import Construct

from brain.cdk.config import BrainConfig


class DatabaseConstruct(Construct):
    """Aurora Serverless v2 PostgreSQL with Data API enabled.

    Uses the default VPC — no custom networking required.
    All access is via the Data API (no VPC connectivity needed from Lambdas).
    """

    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        config: BrainConfig,
    ) -> None:
        super().__init__(scope, id)

        # Use the default VPC for Aurora placement
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)

        self.cluster = rds.DatabaseCluster(
            self,
            "Cluster",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_16_4,
            ),
            default_database_name="cogent",
            enable_data_api=True,
            serverless_v2_min_capacity=config.db_min_acu,
            serverless_v2_max_capacity=config.db_max_acu,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            removal_policy=RemovalPolicy.RETAIN,
            writer=rds.ClusterInstance.serverless_v2("Writer"),
        )

        self.secret = self.cluster.secret
        self.cluster_arn = self.cluster.cluster_arn
