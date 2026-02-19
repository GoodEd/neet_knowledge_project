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

  container_secrets = concat(
    var.openai_api_key_secret_arn != "" ? [{ name = "OPENAI_API_KEY", valueFrom = var.openai_api_key_secret_arn }] : [],
    var.youtube_api_key_secret_arn != "" ? [{ name = "YOUTUBE_API_KEY", valueFrom = var.youtube_api_key_secret_arn }] : []
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
    Statement = [
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
        Resource = compact([
          var.openai_api_key_secret_arn,
          var.youtube_api_key_secret_arn
        ])
      }
    ]
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

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "OPENAI_BASE_URL", value = var.openai_base_url },
        { name = "OPENAI_MODEL_NAME", value = var.openai_model_name },
        { name = "DATA_DIR", value = "/shared/data" },
        { name = "REDIS_URL", value = local.redis_url },
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.ingestion.url }
      ]

      secrets = local.container_secrets

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
        { name = "SQS_QUEUE_URL", value = aws_sqs_queue.ingestion.url }
      ]

      secrets = local.container_secrets

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
  name            = "${local.name_prefix}-streamlit"
  cluster         = data.aws_ecs_cluster.shared.id
  task_definition = aws_ecs_task_definition.streamlit.arn
  desired_count   = var.streamlit_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
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
  name            = "${local.name_prefix}-worker"
  cluster         = data.aws_ecs_cluster.shared.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
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

resource "aws_appautoscaling_policy" "worker_sqs" {
  name               = "${local.name_prefix}-worker-sqs"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value = 10

    customized_metric_specification {
      namespace   = "AWS/SQS"
      metric_name = "ApproximateNumberOfMessagesVisible"
      statistic   = "Average"

      dimensions {
        name  = "QueueName"
        value = aws_sqs_queue.ingestion.name
      }
    }

    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}

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
