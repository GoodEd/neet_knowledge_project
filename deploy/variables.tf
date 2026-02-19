variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "environment" {
  description = "Environment name (dev/stage/prod)"
  type        = string
}

variable "existing_ecs_cluster_name" {
  description = "Existing ECS cluster name"
  type        = string
}

variable "existing_alb_arn" {
  description = "Existing shared ALB ARN"
  type        = string
}

variable "existing_alb_security_group_id" {
  description = "Security group ID attached to existing ALB"
  type        = string
}

variable "shared_certificate_arn" {
  description = "ACM certificate ARN to use on new listener"
  type        = string
}

variable "neet_listener_port" {
  description = "Dedicated HTTPS listener port for this app"
  type        = number
  default     = 7443
}

variable "hosted_zone_name" {
  description = "Route53 hosted zone name, e.g. neetprep.com"
  type        = string
}

variable "app_fqdn" {
  description = "Application FQDN, e.g. pyq.neetprep.com"
  type        = string
}

variable "create_dns_record" {
  description = "Whether to create Route53 alias record"
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "VPC ID where ECS/EFS/Redis will run"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for ECS tasks and EFS mount targets"
  type        = list(string)
}

variable "ecr_streamlit_image" {
  description = "ECR image URI for Streamlit"
  type        = string
}

variable "ecr_worker_image" {
  description = "ECR image URI for worker"
  type        = string
}

variable "streamlit_desired_count" {
  type    = number
  default = 2
}

variable "streamlit_min_capacity" {
  type    = number
  default = 2
}

variable "streamlit_max_capacity" {
  type    = number
  default = 10
}

variable "worker_desired_count" {
  type    = number
  default = 1
}

variable "worker_min_capacity" {
  type    = number
  default = 1
}

variable "worker_max_capacity" {
  type    = number
  default = 4
}

variable "openai_base_url" {
  type    = string
  default = "https://openrouter.ai/api/v1"
}

variable "openai_model_name" {
  type    = string
  default = "google/gemini-2.0-flash-001"
}

variable "openai_api_key_secret_arn" {
  description = "Secrets Manager ARN for OPENAI_API_KEY"
  type        = string
  default     = ""
}

variable "youtube_api_key_secret_arn" {
  description = "Secrets Manager ARN for YOUTUBE_API_KEY"
  type        = string
  default     = ""
}

variable "redis_node_type" {
  type    = string
  default = "cache.t3.micro"
}

variable "redis_num_cache_clusters" {
  type    = number
  default = 2
}

variable "redis_auth_token" {
  description = "Optional Redis AUTH token (leave null to disable auth token)"
  type        = string
  default     = null
  sensitive   = true
}

variable "health_check_path" {
  type    = string
  default = "/"
}

variable "tags" {
  type    = map(string)
  default = {}
}
