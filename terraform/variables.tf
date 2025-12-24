variable "region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-3"
}

variable "project_name" {
  description = "Nom du projet"
  type        = string
  default     = "Steam_Project"
}

variable "group_name" {
  description = "Nom du groupe"
  type        = string
  default     = "G2-MG03"
}

variable "s3_bucket_name" {
  description = "Nom du bucket S3 pour le backend Terraform"
  type        = string
  default     = "terraform-state-g2-mg03"
}

variable "ecr_repo_name" {
  description = "Nom du repository ECR"
  type        = string
  default     = "ecr-g2-mg03"
}

variable "ecs_cluster_name" {
  description = "Nom du cluster ECS"
  type        = string
  default     = "ecs-g2-mg03"
}

variable "ecs_sg_id" {
  description = "ID du Security Group pour MongoDB (à remplir après création ou via data source)"
  type        = string
  default     = ""l
}

variable "service_name" {
  description = "Nom du service App Runner"
  type        = string
  default     = "app-steam-g2-mg03"
}