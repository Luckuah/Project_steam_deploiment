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

module "vpc_G2MG03" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"

  name = "vpc-steam-project"
  cidr = "10.0.0.0/16"

  # On crée des sous-réseaux dans 2 zones pour la haute disponibilité
  azs             = ["eu-west-3a", "eu-west-3b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"] # Pour MongoDB (privé)
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"] # Pour l'accès Internet

  enable_nat_gateway = true # Nécessaire pour que Mongo puisse télécharger des mises à jour
  single_nat_gateway = true
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
  source             = "./modules/ecs"
  cluster_name       = var.ecs_cluster_name
  vpc_id             = module.vpc_G2MG03.vpc_id
  subnet_ids         = module.vpc_G2MG03.private_subnets
  security_group_ids = [var.ecs_sg_id]
}


module "apprunner_G2MG03" {
   source       = "./modules/apprunner"
   service_name = "apprunner-g2-mg03"
    ecr_repo_url = module.ecr_G2MG03.repository_url
    vpc_id       = module.vpc_G2MG03.vpc_id
    subnet_ids   = module.vpc_G2MG03.private_subnet
 }
