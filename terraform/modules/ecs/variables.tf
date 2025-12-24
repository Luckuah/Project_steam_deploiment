variable "cluster_name" {
  type        = string
  description = "Name of the ECS cluster for Mongo"
  default     = "ecs-mongo-g2-mg03"
}

variable "mongo_user" {
  type        = string
  description = "MongoDB root username"
  default     = "User"
}

variable "mongo_password" {
  type        = string
  description = "MongoDB root password"
  default     = "Pass"
}

variable "mongo_db_name" {
  type        = string
  description = "MongoDB database name"
  default     = "Steam_Project"
}

variable "subnet_ids" {
  type        = list(string)
  description = "List of subnet IDs for ECS Fargate"
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security groups for the ECS service"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID where ECS and Cloud Map will reside"
}

variable "ecs_sg_id" {
  type        = string
  description = "Le SG de MongoDB"
}

variable "apprunner_sg_id" {
  type        = string
  description = "Le SG utilisé par le VPC Connector"
}