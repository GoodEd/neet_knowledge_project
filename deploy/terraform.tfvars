aws_region  = "ap-south-1"
environment = "dev"

# Existing shared infrastructure
existing_ecs_cluster_name      = "np-pgrest"
existing_alb_arn               = "arn:aws:elasticloadbalancing:ap-south-1:559387212220:loadbalancer/app/goodedlb/9d02326a4f081eda"
existing_alb_security_group_id = "sg-04591674fcc849d51"

# Listener / certificate
neet_listener_port     = 7443
shared_certificate_arn = "arn:aws:acm:ap-south-1:559387212220:certificate/79433978-2cfe-439f-b6b4-b5dbe672f399"

# DNS
hosted_zone_name  = "neetprep.com"
app_fqdn          = "pyq.neetprep.com"
create_dns_record = true

# Network
vpc_id = "vpc-04631eeddd864b8b3"
private_subnet_ids = [
  "subnet-0d6de2dce64c5edab",
  "subnet-0da960e96ca52559b",
  "subnet-0e4b884bd5bf7a94b"
]

# Images
ecr_streamlit_image = "559387212220.dkr.ecr.ap-south-1.amazonaws.com/neet-knowledge-dev-streamlit:latest"
ecr_worker_image    = "559387212220.dkr.ecr.ap-south-1.amazonaws.com/neet-knowledge-dev-worker:latest"

# Autoscaling
streamlit_desired_count = 2
streamlit_min_capacity  = 2
streamlit_max_capacity  = 10

worker_desired_count = 1
worker_min_capacity  = 1
worker_max_capacity  = 4

# App config
openai_base_url   = "https://openrouter.ai/api/v1"
openai_model_name = "google/gemini-2.0-flash-001"

# Secrets (recommended: keep these in Secrets Manager)
openai_api_key_secret_arn  = "arn:aws:secretsmanager:ap-south-1:559387212220:secret:neet-knowledge/openai-api-key-gycOp3"
youtube_api_key_secret_arn = ""

# Redis
redis_node_type          = "cache.t3.micro"
redis_num_cache_clusters = 2
redis_auth_token         = null

# Health checks
health_check_path = "/"

# CodePipeline / GitHub
codestar_connection_arn = "arn:aws:codestar-connections:ap-south-1:559387212220:connection/ea32a034-fd4a-4720-b389-159fe4319b78"
github_repo_id          = "GoodEd/neet_knowledge_project"
github_branch           = "feature/aws_deployment" # or "main"


tags = {
  Project     = "neet-knowledge"
  Environment = "dev"
  ManagedBy   = "terraform"
}

# Admin UI Password
admin_password = "ihoZfDDpMhARpPjW"
