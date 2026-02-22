resource "aws_iam_role_policy" "ecs_execution_secrets" {
  count = length(local.exec_secret_arns) > 0 ? 1 : 0

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
        Resource = local.exec_secret_arns
      }
    ]
  })
}
