terraform {
  required_version = ">= 1.5.0" [cite: 1]

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0" [cite: 1]
    }
  }

  backend "s3" {
    bucket  = "terraform-state-g2-mg03" [cite: 1]
    key     = "infrastructure/terraform.tfstate" [cite: 1]
    region  = "eu-west-3" [cite: 1]
    encrypt = true [cite: 1]
  }
}

provider "aws" {
  region = var.region [cite: 1]
}

# 1. Création du Réseau (VPC)
module "vpc_G2MG03" {
  source  = "terraform-aws-modules/vpc/aws" [cite: 1]
  version = "5.0.0" [cite: 1]

  name            = "vpc-steam-project" [cite: 2]
  cidr            = "10.0.0.0/16" [cite: 2]

  azs             = ["eu-west-3a", "eu-west-3b"] [cite: 2]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"] [cite: 2]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"] [cite: 2]

  enable_nat_gateway = true [cite: 2]
  single_nat_gateway = true [cite: 2]
}

# 2. Création automatique du Security Group pour MongoDB et l'API (Mise à jour)
resource "aws_security_group" "mongo_sg" {
  name        = "api-sg-g2-mg03" # Nom mis à jour pour refléter l'API
  description = "Autorise le flux entre App Runner, l'API et MongoDB"
  vpc_id      = module.vpc_G2MG03.vpc_id [cite: 2]

  # Autorise MongoDB (27017) depuis l'intérieur du VPC 
  ingress {
    from_port   = 27017 
    to_port     = 27017 
    protocol    = "tcp" 
    cidr_blocks = [module.vpc_G2MG03.vpc_cidr_block] 
  }
  
  # MODIFICATION : On remplace le port 8501 par le port 27099 de ton API
  ingress {
    from_port   = 27099
    to_port     = 27099
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # Permet l'accès public à l'API (HTTP)
  }

  # Autorise la sortie [cite: 4]
  egress {
    from_port   = 0 [cite: 4]
    to_port     = 0 [cite: 4]
    protocol    = "-1" [cite: 4]
    cidr_blocks = ["0.0.0.0/0"] [cite: 4]
  }
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
  vpc_id             = module.vpc_G2MG03.vpc_id [cite: 5]
  subnet_ids         = module.vpc_G2MG03.private_subnets [cite: 5]
  security_group_ids = [aws_security_group.mongo_sg.id]
  ecs_sg_id          = aws_security_group.mongo_sg.id
  apprunner_sg_id    = aws_security_group.mongo_sg.id
}

# 6. Module App Runner (Mise à jour pour l'API)
module "apprunner_G2MG03" {
  source       = "./modules/apprunner"
  service_name = var.service_name
  ecr_repo_url = module.ecr_G2MG03.repository_url_G2_MG03
  subnet_ids   = module.vpc_G2MG03.private_subnets
  sg_ids       = [aws_security_group.mongo_sg.id]
}