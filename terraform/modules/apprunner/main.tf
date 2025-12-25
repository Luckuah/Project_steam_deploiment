# IAM Role for App Runner to access ECR
resource "aws_iam_role" "apprunner_ecr_access_role" {
  name = "${var.service_name}-ecr-access-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "build.apprunner.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = "${var.service_name}-ecr-access-role"
    Environment = "dev"
    Project     = "MLOps-G2MG03"
  }
}

# Attach policy for ECR access
resource "aws_iam_role_policy_attachment" "apprunner_ecr_policy" {
  role       = aws_iam_role.apprunner_ecr_access_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

# IAM Role for App Runner instance (application runtime)
resource "aws_iam_role" "apprunner_instance_role" {
  name = "${var.service_name}-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "tasks.apprunner.amazonaws.com"
      }
    }]
  })

  tags = {
    Name        = "${var.service_name}-instance-role"
    Environment = "dev"
    Project     = "MLOps-G2MG03"
  }
}

# Custom policy for App Runner to access S3 and other services
resource "aws_iam_role_policy" "apprunner_instance_policy" {
  name = "${var.service_name}-instance-policy"
  role = aws_iam_role.apprunner_instance_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_apprunner_vpc_connector" "app_vpc_connector" {
  vpc_connector_name = "app-vpc-connector-g2-mg03"
  subnets            = var.subnet_ids
  security_groups    = var.sg_ids

  tags = {
    Name        = "AppRunnerVPCConnector"
    Project     = "G2-MG03"
  }
}

# 2. Le Service App Runner
resource "aws_apprunner_service" "service" {
  service_name = var.service_name

  # --- CONFIGURATION RÉSEAU (C'est ici qu'on branche le connecteur) ---
  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.app_vpc_connector.arn
    }
  }

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access_role.arn
    }

    image_repository {
      image_identifier      = "${var.ecr_repo_url}:latest"
      image_repository_type = "ECR"

      image_configuration {
        port = "8501" # Port Streamlit (vérifiez votre Dockerfile, c'était 8501 pas 8080)
        
        # --- VARIABLES POUR MONGO ---
        runtime_environment_variables = {
          "DB_IP"   = "mongo.steam.internal" # Nom DNS créé par le module ECS
          "S3_BUCKET" = "terraform-state-g2-mg03"
          "DB_PORT" = "27017"
          "DB_USER" = "User"
          "DB_PASSWORD" = "Pass"
          "DB_NAME" = "Steam_Project"
        }
      }
    }
    auto_deployments_enabled = false
  }

  instance_configuration {
    cpu               = "1024"
    memory            = "2048"
    instance_role_arn = aws_iam_role.apprunner_instance_role.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 5
  }

  tags = {
    Name        = var.service_name
    Environment = "dev"
    Project     = "MLOps-G2MG03"
  }
}




