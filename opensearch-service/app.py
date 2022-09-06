#!/usr/bin/env python3
import os
import json
import random
import string

import aws_cdk as cdk

from aws_cdk import (
  Stack,
  aws_ec2,
  aws_logs,
  aws_opensearchservice,
  aws_secretsmanager
)
from constructs import Construct

random.seed(47)


class OpensearchStack(Stack):

  def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
    super().__init__(scope, construct_id, **kwargs)

    OPENSEARCH_DOMAIN_NAME = cdk.CfnParameter(self, 'OpenSearchDomainName',
      type='String',
      description='Amazon OpenSearch Service domain name',
      default='opensearch-{}'.format(''.join(random.sample((string.ascii_lowercase), k=5))),
      allowed_pattern='[a-z]+[a-z0-9\-]+'
    )

    EC2_KEY_PAIR_NAME = cdk.CfnParameter(self, 'EC2KeyPairName',
      type='String',
      description='Amazon EC2 Instance KeyPair name'
    )

    #XXX: For creating this CDK Stack in the existing VPC,
    # remove comments from the below codes and
    # comments out vpc = aws_ec2.Vpc(..) codes,
    # then pass -c vpc_name=your-existing-vpc to cdk command
    # for example,
    # cdk -c vpc_name=your-existing-vpc syth
    #
    # if you encounter an error such as:
    #  jsii.errors.JavaScriptError:
    #    Error: When providing vpc options you need to provide a subnet for each AZ you are using at new Domain
    # check https://github.com/aws/aws-cdk/issues/12078
    # This error occurs when ZoneAwarenessEnabled in aws_opensearch.Domain(..) is set `true`
    #
    vpc_name = self.node.try_get_context('vpc_name')
    vpc = aws_ec2.Vpc.from_lookup(self, 'ExistingVPC',
      is_default=True,
      vpc_name=vpc_name
    )

    # vpc = aws_ec2.Vpc(self, "OpenSearchVPC",
    #   max_azs=3,
    #   gateway_endpoints={
    #     "S3": aws_ec2.GatewayVpcEndpointOptions(
    #       service=aws_ec2.GatewayVpcEndpointAwsService.S3
    #     )
    #   }
    # )

    #XXX: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_ec2/InstanceClass.html
    #XXX: https://docs.aws.amazon.com/cdk/api/latest/python/aws_cdk.aws_ec2/InstanceSize.html#aws_cdk.aws_ec2.InstanceSize
    ec2_instance_type = aws_ec2.InstanceType.of(aws_ec2.InstanceClass.BURSTABLE3, aws_ec2.InstanceSize.MEDIUM)

    sg_bastion_host = aws_ec2.SecurityGroup(self, "BastionHostSG",
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for an bastion host',
      security_group_name='bastion-host-sg'
    )
    cdk.Tags.of(sg_bastion_host).add('Name', 'bastion-host-sg')

    #TODO: SHOULD restrict IP range allowed to ssh acces
    sg_bastion_host.add_ingress_rule(peer=aws_ec2.Peer.ipv4("0.0.0.0/0"), connection=aws_ec2.Port.tcp(22), description='SSH access')

    bastion_host = aws_ec2.Instance(self, "BastionHost",
      vpc=vpc,
      instance_type=ec2_instance_type,
      machine_image=aws_ec2.MachineImage.latest_amazon_linux(),
      vpc_subnets=aws_ec2.SubnetSelection(subnet_type=aws_ec2.SubnetType.PUBLIC),
      security_group=sg_bastion_host,
      key_name=EC2_KEY_PAIR_NAME.value_as_string
    )

    sg_use_opensearch = aws_ec2.SecurityGroup(self, "OpenSearchClientSG",
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for an opensearch client',
      security_group_name='use-opensearch-cluster-sg'
    )
    cdk.Tags.of(sg_use_opensearch).add('Name', 'use-opensearch-cluster-sg')

    sg_opensearch_cluster = aws_ec2.SecurityGroup(self, "OpenSearchSG",
      vpc=vpc,
      allow_all_outbound=True,
      description='security group for an opensearch cluster',
      security_group_name='opensearch-cluster-sg'
    )
    cdk.Tags.of(sg_opensearch_cluster).add('Name', 'opensearch-cluster-sg')

    sg_opensearch_cluster.add_ingress_rule(peer=sg_opensearch_cluster, connection=aws_ec2.Port.all_tcp(), description='opensearch-cluster-sg')

    sg_opensearch_cluster.add_ingress_rule(peer=sg_use_opensearch, connection=aws_ec2.Port.tcp(443), description='use-opensearch-cluster-sg')
    sg_opensearch_cluster.add_ingress_rule(peer=sg_use_opensearch, connection=aws_ec2.Port.tcp_range(9200, 9300), description='use-opensearch-cluster-sg')

    sg_opensearch_cluster.add_ingress_rule(peer=sg_bastion_host, connection=aws_ec2.Port.tcp(443), description='bastion-host-sg')
    sg_opensearch_cluster.add_ingress_rule(peer=sg_bastion_host, connection=aws_ec2.Port.tcp_range(9200, 9300), description='bastion-host-sg')

    master_user_secret = aws_secretsmanager.Secret(self, "OpenSearchMasterUserSecret",
      generate_secret_string=aws_secretsmanager.SecretStringGenerator(
        secret_string_template=json.dumps({"username": "admin"}),
        generate_string_key="password",
        # Master password must be at least 8 characters long and contain at least one uppercase letter,
        # one lowercase letter, one number, and one special character.
        password_length=8
      )
    )

    #XXX: aws cdk elastsearch example - https://github.com/aws/aws-cdk/issues/2873
    # You should camelCase the property names instead of PascalCase
    # opensearch_domain = aws_opensearchservice.Domain(self, "OpenSearch",
    #   domain_name=OPENSEARCH_DOMAIN_NAME.value_as_string,
    #   version=aws_opensearchservice.EngineVersion.OPENSEARCH_1_0,
    #   capacity={
    #     "master_nodes": 3,
    #     "master_node_instance_type": "r6g.large.search",
    #     "data_nodes": 3,
    #     "data_node_instance_type": "r6g.large.search"
    #   },
    #   ebs={
    #     "volume_size": 10,
    #     "volume_type": aws_ec2.EbsDeviceVolumeType.GP2
    #   },
    #   #XXX: az_count must be equal to vpc subnets count.
    #   zone_awareness={
    #     "availability_zone_count": 3
    #   },
    #   logging={
    #     "slow_search_log_enabled": True,
    #     "app_log_enabled": True,
    #     "slow_index_log_enabled": True
    #   },
    #   fine_grained_access_control=aws_opensearchservice.AdvancedSecurityOptions(
    #     master_user_name=master_user_secret.secret_value_from_json("username").to_string(),
    #     master_user_password=master_user_secret.secret_value_from_json("password")
    #   ),
    #   # Enforce HTTPS is required when fine-grained access control is enabled.
    #   enforce_https=True,
    #   # Node-to-node encryption is required when fine-grained access control is enabled
    #   node_to_node_encryption=True,
    #   # Encryption-at-rest is required when fine-grained access control is enabled.
    #   encryption_at_rest={
    #     "enabled": True
    #   },
    #   use_unsigned_basic_auth=True,
    #   security_groups=[sg_opensearch_cluster],
    #   automated_snapshot_start_hour=17, # 2 AM (GTM+9)
    #   vpc=vpc,
    #   vpc_subnets=[aws_ec2.SubnetSelection(one_per_az=True, subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_NAT)],
    #   removal_policy=cdk.RemovalPolicy.DESTROY # default: cdk.RemovalPolicy.RETAIN
    # )
    # cdk.Tags.of(opensearch_domain).add('Name', f'{OPENSEARCH_DOMAIN_NAME.value_as_string}')

    ops_application_log_group = aws_logs.LogGroup(self, "OpenSearchAppLogs",
      log_group_name=f"/aws/opensearch/{OPENSEARCH_DOMAIN_NAME.value_as_string}/opensearch-application-logs",
      retention=aws_logs.RetentionDays.THREE_DAYS,
      removal_policy=cdk.RemovalPolicy.DESTROY
    )

    ops_slow_index_log_group = aws_logs.LogGroup(self, "OpenSearchSlowIndexLogs",
      log_group_name=f"/aws/opensearch/{OPENSEARCH_DOMAIN_NAME.value_as_string}/opensearch-index-slow-logs",
      retention=aws_logs.RetentionDays.THREE_DAYS,
      removal_policy=cdk.RemovalPolicy.DESTROY
    )

    ops_slow_search_log_group = aws_logs.LogGroup(self, "OpenSearchSlowSearchLogs",
      log_group_name=f"/aws/opensearch/{OPENSEARCH_DOMAIN_NAME.value_as_string}/opensearch-slow-logs",
      retention=aws_logs.RetentionDays.THREE_DAYS,
      removal_policy=cdk.RemovalPolicy.DESTROY
    )

    #XXX: http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-opensearchservice-domain.html
    opensearch_cfn_domain = aws_opensearchservice.CfnDomain(self, "OpenSearchCfnDomain",
      access_policies={
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
              "AWS": "*"
            },
            "Action": [
              "es:Describe*",
              "es:List*",
              "es:Get*",
              "es:ESHttp*"
            ],
            "Resource": self.format_arn(service="es", resource="domain", resource_name=f"{OPENSEARCH_DOMAIN_NAME.value_as_string}/*")
          }
        ]
      },
      advanced_security_options=aws_opensearchservice.CfnDomain.AdvancedSecurityOptionsInputProperty(
        enabled=True,
        internal_user_database_enabled=True,
        master_user_options=aws_opensearchservice.CfnDomain.MasterUserOptionsProperty(
          master_user_name=master_user_secret.secret_value_from_json("username").to_string(),
          master_user_password=master_user_secret.secret_value_from_json("password").to_string()
        )
      ),
      cluster_config=aws_opensearchservice.CfnDomain.ClusterConfigProperty(
        dedicated_master_count=3,
        dedicated_master_enabled=True,
        dedicated_master_type="r6g.large.search",
        instance_count=3,
        instance_type="r6g.large.search",
        zone_awareness_config=aws_opensearchservice.CfnDomain.ZoneAwarenessConfigProperty(
          availability_zone_count=3
        ),
        zone_awareness_enabled=True
      ),
      domain_endpoint_options=aws_opensearchservice.CfnDomain.DomainEndpointOptionsProperty(
        enforce_https=True,
        # optional
        tls_security_policy='Policy-Min-TLS-1-0-2019-07'
      ),
      domain_name=OPENSEARCH_DOMAIN_NAME.value_as_string,
      ebs_options=aws_opensearchservice.CfnDomain.EBSOptionsProperty(
        volume_size=10,
        volume_type="gp2"
      ),
      encryption_at_rest_options=aws_opensearchservice.CfnDomain.EncryptionAtRestOptionsProperty(
        enabled=True
      ),
      engine_version="OpenSearch_1.0",
      log_publishing_options={
        "ES_APPLICATION_LOGS": aws_opensearchservice.CfnDomain.LogPublishingOptionProperty(
          cloud_watch_logs_log_group_arn=ops_application_log_group.log_group_arn,
          enabled=True
        ),
        "SEARCH_SLOW_LOGS": aws_opensearchservice.CfnDomain.LogPublishingOptionProperty(
          cloud_watch_logs_log_group_arn=ops_slow_search_log_group.log_group_arn,
          enabled=True
        ),
        "INDEX_SLOW_LOGS": aws_opensearchservice.CfnDomain.LogPublishingOptionProperty(
          cloud_watch_logs_log_group_arn=ops_slow_index_log_group.log_group_arn,
          enabled=True
        )
      },
      node_to_node_encryption_options=aws_opensearchservice.CfnDomain.NodeToNodeEncryptionOptionsProperty(
        enabled=True
      ),
      snapshot_options=aws_opensearchservice.CfnDomain.SnapshotOptionsProperty(
        automated_snapshot_start_hour=17
      ),
      tags=[cdk.CfnTag(
        key='Name',
        value=f'{OPENSEARCH_DOMAIN_NAME.value_as_string}'
      )],
      vpc_options=aws_opensearchservice.CfnDomain.VPCOptionsProperty(
        security_group_ids=[sg_opensearch_cluster.security_group_id],
        subnet_ids=vpc.select_subnets(subnet_type=aws_ec2.SubnetType.PRIVATE_WITH_NAT).subnet_ids
      )
    )
    opensearch_cfn_domain.apply_removal_policy(cdk.RemovalPolicy.DESTROY) # default: cdk.RemovalPolicy.RETAIN

    cdk.CfnOutput(self, 'BastionHostId', value=bastion_host.instance_id, export_name='BastionHostId')
    # cdk.CfnOutput(self, 'OpenSearchDomainEndpoint', value=opensearch_domain.domain_endpoint, export_name='OpenSearchDomainEndpoint')
    # cdk.CfnOutput(self, 'OpenSearchDashboardsURL', value=f"{opensearch_domain.domain_endpoint}/_dashboards/", export_name='OpenSearchDashboardsURL')
    cdk.CfnOutput(self, 'OpenSearchDomainEndpoint', value=opensearch_cfn_domain.attr_domain_endpoint, export_name='OpenSearchDomainEndpoint')
    cdk.CfnOutput(self, 'OpenSearchDashboardsURL', value=f"{opensearch_cfn_domain.attr_domain_endpoint}/_dashboards/", export_name='OpenSearchDashboardsURL')
    cdk.CfnOutput(self, 'MasterUserSecretId', value=master_user_secret.secret_name, export_name='MasterUserSecretId')


app = cdk.App()
OpensearchStack(app, "OpensearchStack", env=cdk.Environment(
  account=os.getenv('CDK_DEFAULT_ACCOUNT'),
  region=os.getenv('CDK_DEFAULT_REGION')))

app.synth()
