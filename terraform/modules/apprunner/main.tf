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
}

# Custom policy for App Runner to access S3 and logs
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

# VPC Connector pour permettre à App Runner de parler à MongoDB (ECS)
resource "aws_apprunner_vpc_connector" "app_vpc_connector" {
  vpc_connector_name = "app-vpc-connector-g2-mg03"
  subnets            = var.subnet_ids
  security_groups    = var.sg_ids
}

# Service App Runner configuré pour l'API (HTTP)
resource "aws_apprunner_service" "service" {
  service_name = var.service_name

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
        port = "27099" 
        
        runtime_environment_variables = {
          "DB_IP"         = "mongo.steam.internal" 
          "DB_PORT"       = "27017"
          "API_BASE_PORT" = "27099"
          "S3_BUCKET"     = "terraform-state-g2-mg03"
          "DB_NAME"       = "Steam_Project"
          "RUN_DB_IMPORT" = "0" # Optionnel : éviter de réimporter à chaque restart
          "DB_USER" = "User"
          "DB_PASSWORD" = "Pass"
        }
      }
    }
    auto_deployments_enabled = false
  }

  instance_configuration {
    cpu               = "4096"
    memory            = "12288"
    instance_role_arn = aws_iam_role.apprunner_instance_role.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/docs" 
    interval            = 20
    timeout             = 10
    healthy_threshold   = 1
    unhealthy_threshold = 20
  }

  tags = {
    Name        = var.service_name
    Project     = "MLOps-G2MG03"
  }
}