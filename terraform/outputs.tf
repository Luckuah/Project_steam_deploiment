output "s3_bucket_name" {
  description = "Nom du bucket S3 utilisé par Terraform"
  value       = module.s3_G2MG03.bucket_name
}

output "ecr_repository_url" {
  description = "URL du repository ECR"
  value       = module.ecr_G2MG03.repository_url_G2_MG03 # <-- Ajoutez _G2_MG03
}

output "ecs_cluster_arn" {
  description = "ARN du cluster ECS"
  value       = module.ecs_G2MG03.cluster_arn
}
