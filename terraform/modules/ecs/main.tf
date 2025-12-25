# 1️⃣ Private DNS Namespace (Cloud Map)
resource "aws_service_discovery_private_dns_namespace" "steam" {
  name = "steam.internal"
  description = "Private namespace for ECS Mongo"
  vpc  = var.vpc_id
}

# 2️⃣ Service Discovery Service
resource "aws_service_discovery_service" "mongo" {
  name = "mongo"
  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.steam.id
    dns_records {
      type = "A"
      ttl  = 30
    }
  }
}

# 3️⃣ ECS Cluster
resource "aws_ecs_cluster" "mongo_cluster" {
  name = var.cluster_name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = {
    Name        = var.cluster_name
    Environment = "dev"
    Project     = "G2-MG03"
  }
}

# 4️⃣ ECS Task Role
resource "aws_iam_role" "ecs_task_role" {
  name = "${var.cluster_name}-task-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

# 5️⃣ ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.cluster_name}-task-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# 6️⃣ ECS Task Definition
resource "aws_ecs_task_definition" "mongo_task" {
  family                   = "${var.cluster_name}-mongo-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "1024"
  memory                   = "2048"

  ephemeral_storage {
    size_in_gib = 50
  }

  container_definitions = jsonencode([
    {
      name      = "mongo"
      image     = "mongo:7"
      essential = true
      portMappings = [
        { containerPort = 27017, protocol = "tcp" }
      ]
      environment = [
        { name = "MONGO_INITDB_ROOT_USERNAME", value = var.mongo_user },
        { name = "MONGO_INITDB_ROOT_PASSWORD", value = var.mongo_password },
        { name = "MONGO_INITDB_DATABASE", value = var.mongo_db_name }
      ]
    }
  ])
}

# 7️⃣ ECS Service (Fargate)
resource "aws_ecs_service" "mongo_service" {
  name            = "${var.cluster_name}-mongo-service"
  cluster         = aws_ecs_cluster.mongo_cluster.id
  task_definition = aws_ecs_task_definition.mongo_task.arn
  launch_type     = "FARGATE"
  desired_count   = 1

  network_configuration {
    subnets         = var.subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.mongo.arn
  }
}


resource "aws_security_group_rule" "allow_app_to_mongo" {
  type                     = "ingress"
  from_port                = 27017
  to_port                  = 27017
  protocol                 = "tcp"
  security_group_id        = var.ecs_sg_id       # Le SG de MongoDB
  source_security_group_id = var.apprunner_sg_id # Le SG utilisé par le VPC Connector
}