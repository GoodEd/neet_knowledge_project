output "ecs_cluster_name" {
  value = data.aws_ecs_cluster.shared.cluster_name
}

output "streamlit_service_name" {
  value = aws_ecs_service.streamlit.name
}

output "worker_service_name" {
  value = aws_ecs_service.worker.name
}

output "alb_listener_arn" {
  value = aws_lb_listener.neet_https.arn
}

output "alb_listener_port" {
  value = aws_lb_listener.neet_https.port
}

output "target_group_arn" {
  value = aws_lb_target_group.streamlit.arn
}

output "efs_file_system_id" {
  value = aws_efs_file_system.shared.id
}

output "redis_primary_endpoint" {
  value = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "sqs_queue_url" {
  value = aws_sqs_queue.ingestion.url
}

output "app_url" {
  value = "https://${var.app_fqdn}:${var.neet_listener_port}"
}

output "ecs_exec_enabled" {
  value = var.enable_ecs_exec
}
