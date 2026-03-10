locals {
  name_prefix = "neet-knowledge-${var.environment}"

  common_tags = merge(
    {
      Project     = "neet-knowledge"
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags
  )

  redis_url = var.redis_auth_token != null ? format("rediss://:%s@%s:6379/0", var.redis_auth_token, aws_elasticache_replication_group.redis.primary_endpoint_address) : format("redis://%s:6379/0", aws_elasticache_replication_group.redis.primary_endpoint_address)

  streamlit_openai_value = var.streamlit_openai_api_key_secret_arn != "" ? var.streamlit_openai_api_key_secret_arn : var.openai_api_key_secret_arn
  worker_openai_value    = var.worker_openai_api_key_secret_arn != "" ? var.worker_openai_api_key_secret_arn : var.openai_api_key_secret_arn

  streamlit_openai_is_arn = can(regex("^arn:aws:secretsmanager:", local.streamlit_openai_value))
  worker_openai_is_arn    = can(regex("^arn:aws:secretsmanager:", local.worker_openai_value))

  streamlit_container_secrets = concat(
    local.streamlit_openai_value != "" && local.streamlit_openai_is_arn ? [{ name = "OPENAI_API_KEY", valueFrom = local.streamlit_openai_value }] : [],
    var.youtube_api_key_secret_arn != "" ? [{ name = "YOUTUBE_API_KEY", valueFrom = var.youtube_api_key_secret_arn }] : []
  )

  worker_container_secrets = concat(
    local.worker_openai_value != "" && local.worker_openai_is_arn ? [{ name = "OPENAI_API_KEY", valueFrom = local.worker_openai_value }] : [],
    var.youtube_api_key_secret_arn != "" ? [{ name = "YOUTUBE_API_KEY", valueFrom = var.youtube_api_key_secret_arn }] : []
  )

  streamlit_openai_plain_env = local.streamlit_openai_value != "" && !local.streamlit_openai_is_arn ? [{ name = "OPENAI_API_KEY", value = local.streamlit_openai_value }] : []

  openai_secret_arns = compact([
    local.streamlit_openai_is_arn ? local.streamlit_openai_value : "",
    local.worker_openai_is_arn ? local.worker_openai_value : ""
  ])

  exec_secret_arns = concat(
    local.openai_secret_arns,
    var.youtube_api_key_secret_arn != "" ? [var.youtube_api_key_secret_arn] : []
  )
}

data "aws_ecs_cluster" "shared" {
  cluster_name = var.existing_ecs_cluster_name
}

data "aws_lb" "shared" {
  arn = var.existing_alb_arn
}

data "aws_route53_zone" "main" {
  count        = var.create_dns_record ? 1 : 0
  name         = var.hosted_zone_name
  private_zone = false
}

resource "aws_security_group" "ecs_tasks" {
  name        = "${local.name_prefix}-ecs-tasks"
  description = "Security group for ECS tasks"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_security_group_rule" "alb_to_streamlit" {
  type                     = "ingress"
  from_port                = 8501
  to_port                  = 8501
  protocol                 = "tcp"
  source_security_group_id = var.existing_alb_security_group_id
  security_group_id        = aws_security_group.ecs_tasks.id
}

resource "aws_security_group" "efs" {
  name        = "${local.name_prefix}-efs"
  description = "Security group for EFS"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_security_group_rule" "ecs_to_efs" {
  type                     = "ingress"
  from_port                = 2049
  to_port                  = 2049
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  security_group_id        = aws_security_group.efs.id
}

resource "aws_security_group" "redis" {
  name        = "${local.name_prefix}-redis"
  description = "Security group for Redis"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

resource "aws_security_group_rule" "ecs_to_redis" {
  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_tasks.id
  security_group_id        = aws_security_group.redis.id
}

resource "aws_sqs_queue" "ingestion" {
  name                       = "${local.name_prefix}-ingestion"
  visibility_timeout_seconds = 300
  message_retention_seconds  = 1209600

  tags = local.common_tags
}

resource "aws_s3_bucket" "backup" {
  bucket = "${local.name_prefix}-backup"

  tags = local.common_tags
}

resource "aws_s3_bucket_lifecycle_configuration" "backup_lifecycle" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "expire-old"
    status = "Enabled"

    expiration {
      days = 90
    }
  }
}

resource "aws_efs_file_system" "shared" {
  creation_token = local.name_prefix
  encrypted      = true

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = local.common_tags
}

resource "aws_efs_mount_target" "shared" {
  for_each = toset(var.private_subnet_ids)

  file_system_id  = aws_efs_file_system.shared.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}

resource "aws_efs_access_point" "shared" {
  file_system_id = aws_efs_file_system.shared.id

  root_directory {
    path = "/shared"
    creation_info {
      owner_uid   = "1000"
      owner_gid   = "1000"
      permissions = "755"
    }
  }

  posix_user {
    uid = 1000
    gid = 1000
  }

  tags = local.common_tags
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.name_prefix}-redis-subnets"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = replace(local.name_prefix, "_", "-")
  description                = "Redis for ${local.name_prefix}"
  engine                     = "redis"
  engine_version             = "7.0"
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.redis_num_cache_clusters
  subnet_group_name          = aws_elasticache_subnet_group.redis.name
  security_group_ids         = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = var.redis_auth_token

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "streamlit" {
  name              = "/ecs/${local.name_prefix}-streamlit"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.name_prefix}-worker"
  retention_in_days = 30
}

resource "aws_iam_role" "ecs_execution" {
  name = "${local.name_prefix}-ecs-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution_base" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task" {
  name = "${local.name_prefix}-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "ecs_task_inline" {
  name = "${local.name_prefix}-task-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:GetQueueUrl"
        ]
        Resource = aws_sqs_queue.ingestion.arn
      },
      {
        Effect = "Allow"
        Action = [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientRootAccess"
        ]
        Resource = [
          aws_efs_file_system.shared.arn,
          aws_efs_access_point.shared.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = concat(
          local.openai_secret_arns,
          var.youtube_api_key_secret_arn != "" ? [var.youtube_api_key_secret_arn] : []
        )
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion"
        ]
        Resource = [
          "arn:aws:s3:::${var.asset_bucket_name}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.asset_bucket_name}"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel"
        ]
        Resource = "*"
      }
      ],
      length(var.asset_kms_key_arns) > 0 ? [{
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = var.asset_kms_key_arns
      }] : []
    )
  })
}

resource "aws_lb_target_group" "streamlit" {
  name        = substr("neet-streamlit-${var.environment}", 0, 32)
  port        = 8501
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.health_check_path
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  tags = local.common_tags
}

resource "aws_lb_listener" "neet_https" {
  load_balancer_arn = data.aws_lb.shared.arn
  port              = var.neet_listener_port
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = var.shared_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.streamlit.arn
  }

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "streamlit" {
  family                   = "${local.name_prefix}-streamlit"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  volume {
    name = "shared-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.shared.id
      root_directory     = "/"
      transit_encryption = "ENABLED"

      authorization_config {
        access_point_id = aws_efs_access_point.shared.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "streamlit"
      image     = var.ecr_streamlit_image
      essential = true

      portMappings = [
        {
          containerPort = 8501
          protocol      = "tcp"
        }
      ]

      environment = concat([
        { name = "AWS_REGION", value = var.aws_region },
        { name = "OPENAI_BASE_URL", value = var.openai_base_url },
        { name = "OPENAI_MODEL_NAME", value = var.openai_model_name },
        { name = "DATA_DIR", value = "/shared/data" },
        { name = "REDIS_URL", value = local.redis_url },
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.ingestion.url },
        { name = "CHAT_HISTORY_TURNS", value = tostring(var.chat_history_turns) },
        { name = "ADMIN_PASSWORD", value = var.admin_password },
        { name = "SHOW_MORE_ENABLED", value = var.show_more_enabled },
        { name = "SHOW_QUESTION_SOURCES", value = var.show_question_sources },
        { name = "ASK_ASSISTANT_ENABLED", value = var.ask_assistant_enabled }
      ], local.streamlit_openai_plain_env)

      secrets = local.streamlit_container_secrets

      mountPoints = [
        {
          sourceVolume  = "shared-data"
          containerPath = "/shared/data"
          readOnly      = false
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.streamlit.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  volume {
    name = "shared-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.shared.id
      root_directory     = "/"
      transit_encryption = "ENABLED"

      authorization_config {
        access_point_id = aws_efs_access_point.shared.id
        iam             = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.ecr_worker_image
      essential = true

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "OPENAI_BASE_URL", value = var.openai_base_url },
        { name = "OPENAI_MODEL_NAME", value = var.openai_model_name },
        { name = "DATA_DIR", value = "/shared/data" },
        { name = "REDIS_URL", value = local.redis_url },
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.ingestion.url },
        { name = "ADMIN_PASSWORD", value = var.admin_password }
      ]

      secrets = local.worker_container_secrets

      mountPoints = [
        {
          sourceVolume  = "shared-data"
          containerPath = "/shared/data"
          readOnly      = false
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
    }
  ])

  tags = local.common_tags
}

resource "aws_ecs_service" "streamlit" {
  name                   = "${local.name_prefix}-streamlit"
  cluster                = data.aws_ecs_cluster.shared.id
  task_definition        = aws_ecs_task_definition.streamlit.arn
  desired_count          = var.streamlit_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = var.enable_ecs_exec

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.streamlit.arn
    container_name   = "streamlit"
    container_port   = 8501
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.neet_https]

  tags = local.common_tags
}

resource "aws_ecs_service" "worker" {
  name                   = "${local.name_prefix}-worker"
  cluster                = data.aws_ecs_cluster.shared.id
  task_definition        = aws_ecs_task_definition.worker.arn
  desired_count          = var.worker_desired_count
  launch_type            = "FARGATE"
  enable_execute_command = var.enable_ecs_exec

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = local.common_tags
}

resource "aws_appautoscaling_target" "streamlit" {
  service_namespace  = "ecs"
  resource_id        = "service/${data.aws_ecs_cluster.shared.cluster_name}/${aws_ecs_service.streamlit.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.streamlit_min_capacity
  max_capacity       = var.streamlit_max_capacity
}

resource "aws_appautoscaling_policy" "streamlit_cpu" {
  name               = "${local.name_prefix}-streamlit-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.streamlit.service_namespace
  resource_id        = aws_appautoscaling_target.streamlit.resource_id
  scalable_dimension = aws_appautoscaling_target.streamlit.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_target" "worker" {
  service_namespace  = "ecs"
  resource_id        = "service/${data.aws_ecs_cluster.shared.cluster_name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.worker_min_capacity
  max_capacity       = var.worker_max_capacity
}

resource "aws_appautoscaling_policy" "worker_scale_out" {
  name               = "${local.name_prefix}-worker-scale-out"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 30
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_lower_bound = 0
      scaling_adjustment          = 1
    }
  }
}

resource "aws_appautoscaling_policy" "worker_scale_in" {
  name               = "${local.name_prefix}-worker-scale-in"
  policy_type        = "StepScaling"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension

  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 90
    metric_aggregation_type = "Maximum"

    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = -1
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_sqs_messages_high" {
  alarm_name          = "${local.name_prefix}-worker-sqs-messages-high"
  alarm_description   = "Scale out worker when SQS queue has messages"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.ingestion.name
  }

  alarm_actions = [aws_appautoscaling_policy.worker_scale_out.arn]
}

resource "aws_cloudwatch_metric_alarm" "worker_sqs_messages_low" {
  alarm_name          = "${local.name_prefix}-worker-sqs-messages-low"
  alarm_description   = "Scale in worker when SQS queue is empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 10
  threshold           = 0
  comparison_operator = "LessThanOrEqualToThreshold"
  treat_missing_data  = "breaching"

  dimensions = {
    QueueName = aws_sqs_queue.ingestion.name
  }

  alarm_actions = [aws_appautoscaling_policy.worker_scale_in.arn]
}


resource "aws_ecr_repository" "streamlit" {
  name                 = "${local.name_prefix}-streamlit"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_ecr_repository" "worker" {
  name                 = "${local.name_prefix}-worker"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

resource "aws_codebuild_project" "build" {
  name          = "${local.name_prefix}-build"
  description   = "Builds Docker images for ${local.name_prefix}"
  build_timeout = "60"
  service_role  = aws_iam_role.codebuild.arn

  artifacts {
    type = "CODEPIPELINE"
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux2-aarch64-standard:3.0"
    type                        = "ARM_CONTAINER"
    image_pull_credentials_type = "CODEBUILD"
    privileged_mode             = true

    environment_variable {
      name  = "AWS_DEFAULT_REGION"
      value = var.aws_region
    }
    environment_variable {
      name  = "AWS_ACCOUNT_ID"
      value = data.aws_caller_identity.current.account_id
    }
    environment_variable {
      name  = "IMAGE_REPO_NAME_STREAMLIT"
      value = aws_ecr_repository.streamlit.name
    }
    environment_variable {
      name  = "IMAGE_REPO_NAME_WORKER"
      value = aws_ecr_repository.worker.name
    }
    environment_variable {
      name  = "IMAGE_TAG"
      value = "latest"
    }
    environment_variable {
      name  = "ECS_CLUSTER_NAME"
      value = data.aws_ecs_cluster.shared.cluster_name
    }
    environment_variable {
      name  = "ECS_SERVICE_STREAMLIT"
      value = aws_ecs_service.streamlit.name
    }
    environment_variable {
      name  = "ECS_SERVICE_WORKER"
      value = aws_ecs_service.worker.name
    }
  }

  source {
    type      = "CODEPIPELINE"
    buildspec = "buildspec.yml"
  }

  tags = local.common_tags
}

resource "aws_codepipeline" "main" {
  name     = "${local.name_prefix}-pipeline"
  role_arn = aws_iam_role.codepipeline.arn

  artifact_store {
    location = aws_s3_bucket.codepipeline.bucket
    type     = "S3"
  }

  stage {
    name = "Source"

    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["source_output"]

      configuration = {
        ConnectionArn        = var.codestar_connection_arn
        FullRepositoryId     = var.github_repo_id
        BranchName           = var.github_branch
        OutputArtifactFormat = "CODEBUILD_CLONE_REF"
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "Build"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      input_artifacts  = ["source_output"]
      output_artifacts = ["build_output"]
      version          = "1"

      configuration = {
        ProjectName = aws_codebuild_project.build.name
      }
    }
  }

  stage {
    name = "Deploy"

    action {
      name            = "DeployStreamlit"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ECS"
      input_artifacts = ["build_output"]
      version         = "1"

      configuration = {
        ClusterName = data.aws_ecs_cluster.shared.cluster_name
        ServiceName = aws_ecs_service.streamlit.name
        FileName    = "imagedefinitions_streamlit.json"
      }
    }

    action {
      name            = "DeployWorker"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "ECS"
      input_artifacts = ["build_output"]
      version         = "1"

      configuration = {
        ClusterName = data.aws_ecs_cluster.shared.cluster_name
        ServiceName = aws_ecs_service.worker.name
        FileName    = "imagedefinitions_worker.json"
      }
    }
  }

  tags = local.common_tags
}

resource "aws_s3_bucket" "codepipeline" {
  bucket = "${local.name_prefix}-codepipeline"
  tags   = local.common_tags
}

resource "aws_iam_role" "codebuild" {
  name = "${local.name_prefix}-codebuild"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "codebuild.amazonaws.com"
        }
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "codebuild" {
  role = aws_iam_role.codebuild.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Resource = [
          "*"
        ]
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.codepipeline.arn,
          "${aws_s3_bucket.codepipeline.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:GetRepositoryPolicy",
          "ecr:DescribeRepositories",
          "ecr:ListImages",
          "ecr:DescribeImages",
          "ecr:BatchGetImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:DescribeTaskDefinition"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "codestar-connections:UseConnection"
        ]
        Resource = var.codestar_connection_arn
      }
    ]
  })
}

resource "aws_iam_role" "codepipeline" {
  name = "${local.name_prefix}-codepipeline"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "codepipeline.amazonaws.com"
        }
      }
    ]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy" "codepipeline" {
  role = aws_iam_role.codepipeline.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:GetBucketVersioning"
        ]
        Resource = [
          aws_s3_bucket.codepipeline.arn,
          "${aws_s3_bucket.codepipeline.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "codebuild:BatchGetBuilds",
          "codebuild:StartBuild"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "codestar-connections:UseConnection"
        ]
        Resource = var.codestar_connection_arn
      },
      {
        Effect = "Allow"
        Action = [
          "ecs:*"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "iam:PassRole"
        ]
        Resource = "*"
      }
    ]
  })
}

data "aws_caller_identity" "current" {}

resource "aws_route53_record" "app" {
  count   = var.create_dns_record ? 1 : 0
  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = var.app_fqdn
  type    = "A"

  alias {
    name                   = data.aws_lb.shared.dns_name
    zone_id                = data.aws_lb.shared.zone_id
    evaluate_target_health = true
  }
}
