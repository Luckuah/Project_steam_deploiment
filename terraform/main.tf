terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket  = "terraform-state-g2-mg03" # Nom réel du bucket
    key     = "infrastructure/terraform.tfstate"
    region  = "eu-west-3"               # Région réelle
    encrypt = true
  }
}

provider "aws" {
  region = var.region
}

# --------------------------
# S3 Bucket Module
# --------------------------
module "s3_G2MG03" {
  source      = "./modules/s3"
  bucket_name = var.s3_bucket_name
}

# --------------------------
# ECR Repository Module
# --------------------------
module "ecr_G2MG03" {
  source    = "./modules/ecr"
  repo_name = var.ecr_repo_name
}

# --------------------------
# ECS Cluster Module
# --------------------------
module "ecs_G2MG03" {
  source       = "./modules/ecs"
  cluster_name = var.ecs_cluster_name
}

# --------------------------
# App Runner Service Module (optionnel)
# --------------------------
# module "apprunner_G2MG03" {
#   source       = "./modules/apprunner"
#   service_name = "apprunner-g2-mg03"
#   ecr_repo_url = module.ecr_G2MG03.repository_url
# }
