terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket  = "terraform-state-g2-mg03"
    key     = "infrastructure/terraform.tfstate"
    region  = "eu-west-3"
    encrypt = true
  }
}

provider "aws" {
  region = var.region
}

# 1. Création du Réseau (VPC)
module "vpc_G2MG03" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"

  name = "vpc-steam-project"
  cidr = "10.0.0.0/16"

  azs             = ["eu-west-3a", "eu-west-3b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = true
}

# 2. Création automatique du Security Group pour MongoDB et App Runner
resource "aws_security_group" "mongo_sg" {
  name        = "mongo-sg-g2-mg03"
  description = "Autorise le flux entre App Runner et MongoDB"
  vpc_id      = module.vpc_G2MG03.vpc_id

  # Autorise MongoDB (27017) depuis l'intérieur du VPC
  ingress {
    from_port   = 27017
    to_port     = 27017
    protocol    = "tcp"
    cidr_blocks = [module.vpc_G2MG03.vpc_cidr_block]
  }

  # Autorise la sortie (nécessaire pour télécharger des images/mises à jour)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 3. Module S3
module "s3_G2MG03" {
  source      = "./modules/s3"
  bucket_name = var.s3_bucket_name
}

# 4. Module ECR
module "ecr_G2MG03" {
  source    = "./modules/ecr"
  repo_name = var.ecr_repo_name
}

# 5. Module ECS (MongoDB)
module "ecs_G2MG03" {
  source             = "./modules/ecs"
  cluster_name       = var.ecs_cluster_name
  vpc_id             = module.vpc_G2MG03.vpc_id
  subnet_ids         = module.vpc_G2MG03.private_subnets
  security_group_ids = [aws_security_group.mongo_sg.id] # <-- Utilisation de la ressource créée au dessus
  ecs_sg_id          = aws_security_group.mongo_sg.id
  apprunner_sg_id    = aws_security_group.mongo_sg.id
}

# 6. Module App Runner
module "apprunner_G2MG03" {
  source       = "./modules/apprunner"
  service_name = var.service_name
  ecr_repo_url = module.ecr_G2MG03.repository_url_G2_MG03
  subnet_ids   = module.vpc_G2MG03.private_subnets
  sg_ids       = [aws_security_group.mongo_sg.id] # <-- Utilisation de la ressource créée au dessus
}