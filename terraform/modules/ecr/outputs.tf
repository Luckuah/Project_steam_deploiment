# outputs.tf
output "repository_url_G2_MG03" {
  description = "The URL of the ECR repository"
  value       = aws_ecr_repository.repo.repository_url
}

output "repository_arn_G2_MG03" {
  description = "The ARN of the ECR repository"
  value       = aws_ecr_repository.repo.arn
}

output "repository_name_G2_MG03" {
  description = "The name of the ECR repository"
  value       = aws_ecr_repository.repo.name
}