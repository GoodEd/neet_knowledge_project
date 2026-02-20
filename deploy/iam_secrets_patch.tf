resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "${local.name_prefix}-exec-secrets-policy"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
